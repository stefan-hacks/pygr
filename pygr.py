#!/usr/bin/env python3
"""
pygr - Python GitHub Repository package manager
Single-file implementation with all advanced features:
- GitHub source fetching with tree hashing
- SAT-like dependency resolution with version constraints
- Sandboxed builds (via firejail)
- Content-addressed store
- Binary cache support
- Transactional profile generations (rollbacks)
- Install, uninstall, upgrade commands
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from typing import Any, Dict, List
from urllib.parse import urljoin

import git  # requires GitPython
import requests  # requires requests
import yaml  # requires PyYAML
from packaging import version as pkg_version  # requires packaging

# ==================== Configuration ====================
PYGR_ROOT = os.environ.get("PYGR_ROOT", os.path.expanduser("~/.local/share/pygr"))
STORE_ROOT = os.path.join(PYGR_ROOT, "store")
PROFILE_DIR = os.path.join(PYGR_ROOT, "profiles")
REPO_CACHE = os.path.join(PYGR_ROOT, "repos")
DB_PATH = os.path.join(PYGR_ROOT, "pygr.db")
SOURCE_CACHE = os.path.join(STORE_ROOT, "sources")

# Ensure directories exist
os.makedirs(STORE_ROOT, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)
os.makedirs(REPO_CACHE, exist_ok=True)
os.makedirs(SOURCE_CACHE, exist_ok=True)


# ==================== Utility Functions ====================
def logger(msg, level="INFO"):
    print(f"[{level}] {msg}")


def run_cmd(cmd, cwd=None, env=None, check=True, capture_output=False):
    """Run shell command and return result."""
    if capture_output:
        result = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd)
        return result
    else:
        subprocess.run(cmd, shell=True, cwd=cwd, env=env, check=check)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def compute_hash(data: Dict[str, Any]) -> str:
    """SHA256 of canonical JSON."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ==================== Database ====================
class Database:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS store_packages (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                store_path TEXT NOT NULL,
                install_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS repos (
                name TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                type TEXT DEFAULT 'github'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                generation INTEGER NOT NULL,
                packages TEXT NOT NULL,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def add_store_package(self, store_id, name, version, store_path):
        c = self.conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO store_packages (id, name, version, store_path) VALUES (?,?,?,?)",
            (store_id, name, version, store_path),
        )
        self.conn.commit()

    def get_store_package(self, store_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM store_packages WHERE id=?", (store_id,))
        return c.fetchone()

    def add_repo(self, name, url, repo_type="github"):
        c = self.conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO repos (name, url, type) VALUES (?,?,?)", (name, url, repo_type)
        )
        self.conn.commit()

    def list_repos(self):
        c = self.conn.cursor()
        c.execute("SELECT name, url FROM repos")
        return c.fetchall()

    def add_profile_generation(self, profile_name, generation, packages):
        c = self.conn.cursor()
        c.execute(
            "INSERT INTO profiles (name, generation, packages) VALUES (?,?,?)",
            (profile_name, generation, json.dumps(packages)),
        )
        self.conn.commit()

    def get_latest_profile_generation(self, profile_name):
        c = self.conn.cursor()
        c.execute(
            "SELECT generation, packages FROM profiles WHERE name=? ORDER BY generation DESC LIMIT 1",
            (profile_name,),
        )
        row = c.fetchone()
        if row:
            return row[0], json.loads(row[1])
        return None, None

    def get_profile_generation(self, profile_name, generation):
        c = self.conn.cursor()
        c.execute(
            "SELECT packages FROM profiles WHERE name=? AND generation=?",
            (profile_name, generation),
        )
        row = c.fetchone()
        if row:
            return json.loads(row[0])
        return None


# ==================== Recipe ====================
class Recipe:
    def __init__(self, data: Dict[str, Any]):
        self.name = data["name"]
        self.version = data["version"]
        self.source = data["source"]
        self.build = data.get("build", {})
        self.install = data.get("install", {})
        self.dependencies = data.get("dependencies", [])
        self._validate()

    def _validate(self):
        assert self.source.get("type") == "github", "Only GitHub sources supported"
        assert "repo" in self.source
        assert "ref" in self.source

    def to_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "build": self.build,
            "install": self.install,
            "dependencies": self.dependencies,
        }


def load_recipe_file(path: str) -> Recipe:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Recipe(data)


def find_recipes_in_dir(directory: str) -> List[Recipe]:
    recipes = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith((".yaml", ".yml")):
                try:
                    recipes.append(load_recipe_file(os.path.join(root, file)))
                except Exception as e:
                    logger(f"Could not load {file}: {e}", "WARNING")
    return recipes


# ==================== Source Fetcher ====================
class SourceFetcher:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir

    def _compute_tree_hash(self, directory):
        hasher = hashlib.sha256()
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d != ".git"]
            for file in sorted(files):
                path = os.path.join(root, file)
                relpath = os.path.relpath(path, directory)
                hasher.update(relpath.encode())
                with open(path, "rb") as f:
                    hasher.update(f.read())
        return hasher.hexdigest()

    def fetch(self, recipe, force_refetch=False):
        source = recipe.source
        repo_url = f"https://github.com/{source['repo']}.git"
        ref = source["ref"]

        # Get exact commit hash
        if len(ref) == 40:
            commit_hash = ref
        else:
            output = run_cmd(f"git ls-remote {repo_url} {ref}", capture_output=True)
            commit_hash = output.stdout.split()[0] if output.stdout else None
            if not commit_hash:
                raise Exception(f"Could not resolve ref {ref} for {repo_url}")

        cache_key = f"{source['repo'].replace('/', '_')}_{commit_hash}"
        cache_path = os.path.join(self.cache_dir, cache_key)

        if os.path.exists(cache_path) and not force_refetch:
            logger(f"Using cached source at {cache_path}")
            return cache_path, self._compute_tree_hash(cache_path)

        logger(f"Fetching source from {repo_url} at commit {commit_hash}")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = git.Repo.clone_from(repo_url, tmpdir, depth=1, no_checkout=True)
            repo.git.fetch("--depth=1", "origin", commit_hash)
            repo.git.checkout(commit_hash)
            tree_hash = self._compute_tree_hash(tmpdir)
            shutil.copytree(tmpdir, cache_path)
            return cache_path, tree_hash


# ==================== Store ====================
class Store:
    def __init__(self, store_root=STORE_ROOT):
        self.root = store_root
        ensure_dir(self.root)
        self.db = Database()

    def compute_derivation_hash(self, recipe, source_hash, dep_hashes):
        data = {
            "recipe": recipe.to_dict(),
            "source_hash": source_hash,
            "dependencies": sorted(dep_hashes),
        }
        return compute_hash(data)

    def add_package(self, recipe, source_hash, dep_hashes, build_output_dir):
        store_hash = self.compute_derivation_hash(recipe, source_hash, dep_hashes)
        store_path = os.path.join(self.root, f"{store_hash}-{recipe.name}-{recipe.version}")
        if os.path.exists(store_path):
            logger(f"Package already exists in store: {store_path}")
            return store_path

        logger(f"Installing to store: {store_path}")
        shutil.copytree(build_output_dir, store_path)
        self.db.add_store_package(store_hash, recipe.name, recipe.version, store_path)
        return store_path

    def get_package_path(self, store_hash):
        row = self.db.get_store_package(store_hash)
        if row:
            return row[3]
        return None


# ==================== Binary Cache ====================
class BinaryCache:
    def __init__(self, cache_url=None):
        self.cache_url = cache_url

    def fetch(self, store_hash, store_path):
        if not self.cache_url:
            return False
        url = urljoin(self.cache_url, f"{store_hash}.tar.gz")
        try:
            resp = requests.get(url, stream=True, timeout=10)
            if resp.status_code == 200:
                logger(f"Downloading pre-built package from cache: {store_hash}")
                with tempfile.TemporaryFile() as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                    f.seek(0)
                    with tempfile.TemporaryDirectory() as tmpdir:
                        with tarfile.open(fileobj=f, mode="r:gz") as tar:
                            tar.extractall(path=tmpdir)
                        items = os.listdir(tmpdir)
                        if len(items) == 1 and os.path.isdir(os.path.join(tmpdir, items[0])):
                            shutil.move(os.path.join(tmpdir, items[0]), store_path)
                        else:
                            ensure_dir(store_path)
                            for item in items:
                                shutil.move(
                                    os.path.join(tmpdir, item), os.path.join(store_path, item)
                                )
                return True
            else:
                return False
        except Exception as e:
            logger(f"Cache fetch failed: {e}", "WARNING")
            return False


# ==================== Builder ====================
class Builder:
    def __init__(self, store, use_sandbox=True):
        self.store = store
        self.use_sandbox = use_sandbox
        self.sandbox_cmd = None
        if use_sandbox:
            if shutil.which("firejail"):
                self.sandbox_cmd = ["firejail", "--quiet", "--noprofile"]
                logger("Using firejail for build isolation")
            else:
                logger("firejail not found, builds will run without sandbox", "WARNING")
                self.use_sandbox = False

    def build(self, recipe, source_dir, dep_paths):
        with tempfile.TemporaryDirectory() as build_dir:
            shutil.copytree(source_dir, build_dir, dirs_exist_ok=True)

            env = os.environ.copy()
            extra_paths = [
                os.path.join(p, "bin") for p in dep_paths if os.path.exists(os.path.join(p, "bin"))
            ]
            if extra_paths:
                env["PATH"] = ":".join(extra_paths) + ":" + env.get("PATH", "")

            install_prefix = os.path.join(build_dir, "install-root")
            os.makedirs(install_prefix)

            def run_in_sandbox(cmd, cwd):
                if self.use_sandbox and self.sandbox_cmd:
                    full_cmd = self.sandbox_cmd + [
                        f"--whitelist={build_dir}",
                        "--private",
                        "--net=none",
                        "--noroot",
                        "--",
                        "/bin/sh",
                        "-c",
                        cmd,
                    ]
                    subprocess.run(full_cmd, cwd=cwd, env=env, check=True)
                else:
                    run_cmd(cmd, cwd=cwd, env=env, check=True)

            # Build commands
            for cmd in recipe.build.get("commands", []):
                cmd = cmd.replace("{{prefix}}", install_prefix)
                run_in_sandbox(cmd, build_dir)

            # Install commands
            for cmd in recipe.install.get("commands", []):
                cmd = cmd.replace("{{prefix}}", install_prefix)
                run_in_sandbox(cmd, build_dir)

            return install_prefix


# ==================== Version Constraint ====================
class VersionConstraint:
    def __init__(self, spec: str):
        self.spec = spec.strip()
        self.op = ""
        self.version = None
        if self.spec:
            match = re.match(r"^(==|>=|<=|>|<)?\s*(.*)$", self.spec)
            if match:
                self.op = match.group(1) or "=="
                self.version = match.group(2).strip()
            else:
                raise ValueError(f"Invalid version spec: {spec}")
        else:
            self.op = "any"

    def matches(self, ver_str: str) -> bool:
        if self.op == "any" or self.version is None:
            return True
        ver = pkg_version.parse(ver_str)
        target = pkg_version.parse(self.version)
        if self.op == "==":
            return ver == target
        elif self.op == ">=":
            return ver >= target
        elif self.op == "<=":
            return ver <= target
        elif self.op == ">":
            return ver > target
        elif self.op == "<":
            return ver < target
        return False


# ==================== Resolver ====================
class Resolver:
    def __init__(self, recipes_by_name: Dict[str, List[Recipe]]):
        self.recipes_by_name = recipes_by_name

    def resolve(self, root_name: str, version_spec: str = "") -> List[Recipe]:
        self.seen: set[str] = set()
        self.selected: Dict[str, Recipe] = {}
        self._resolve_deps(root_name, version_spec, [])
        # topological order
        order = []
        visited = set()

        def visit(name):
            if name in visited:
                return
            visited.add(name)
            recipe = self.selected[name]
            for dep in recipe.dependencies:
                dep_name = dep.split(">")[0].split("<")[0].split("=")[0].strip()
                visit(dep_name)
            order.append(recipe)

        visit(root_name)
        return order

    def _resolve_deps(self, name: str, version_spec: str, path: List[str]):
        if name in path:
            raise Exception(f"Circular dependency: {' -> '.join(path + [name])}")
        if name in self.selected:
            chosen = self.selected[name]
            if version_spec and not VersionConstraint(version_spec).matches(chosen.version):
                raise Exception(
                    f"Incompatible requirement: {name}{version_spec} but already selected {chosen.name}=={chosen.version}"
                )
            return

        recipes = self.recipes_by_name.get(name, [])
        if not recipes:
            raise Exception(f"No recipe found for {name}")

        constraint = VersionConstraint(version_spec)
        candidates = [r for r in recipes if constraint.matches(r.version)]
        if not candidates:
            raise Exception(f"No version of {name} satisfies {version_spec}")

        candidates.sort(key=lambda r: pkg_version.parse(r.version), reverse=True)
        chosen = candidates[0]
        self.selected[name] = chosen

        for dep in chosen.dependencies:
            dep_name = dep.split(">")[0].split("<")[0].split("=")[0].strip()
            dep_spec = dep[len(dep_name) :].strip()
            self._resolve_deps(dep_name, dep_spec, path + [name])


# ==================== Repo Manager ====================
class RepoManager:
    def __init__(self):
        ensure_dir(REPO_CACHE)

    def add_repo(self, name, url):
        dest = os.path.join(REPO_CACHE, name)
        if os.path.exists(dest):
            logger(f"Repo {name} already exists, updating...")
            repo = git.Repo(dest)
            repo.remotes.origin.pull()
        else:
            logger(f"Cloning repo {url} to {dest}")
            git.Repo.clone_from(url, dest)
        db = Database()
        db.add_repo(name, url)
        db.close()

    def list_recipes(self) -> List[Recipe]:
        recipes = []
        for repo_name in os.listdir(REPO_CACHE):
            repo_path = os.path.join(REPO_CACHE, repo_name)
            if os.path.isdir(repo_path):
                recipes.extend(find_recipes_in_dir(repo_path))
        return recipes

    def index_recipes_by_name(self) -> Dict[str, List[Recipe]]:
        recipes = self.list_recipes()
        by_name: Dict[str, List[Recipe]] = {}
        for r in recipes:
            by_name.setdefault(r.name, []).append(r)
        return by_name


# ==================== Profile ====================
class Profile:
    def __init__(self, name="default"):
        self.name = name
        self.dir = os.path.join(PROFILE_DIR, name)
        ensure_dir(self.dir)
        self.db = Database()

    def current_generation(self):
        gen, pkgs = self.db.get_latest_profile_generation(self.name)
        if gen is None:
            return 0, []
        return gen, pkgs

    def switch_to_generation(self, generation):
        pkgs = self.db.get_profile_generation(self.name, generation)
        if pkgs is None:
            raise Exception(f"Generation {generation} not found")
        bin_dir = os.path.join(self.dir, "bin")
        ensure_dir(bin_dir)
        # Clear bin dir (files, symlinks, and subdirs)
        for name in os.listdir(bin_dir):
            path = os.path.join(bin_dir, name)
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        store = Store()
        for store_id in pkgs:
            store_path = store.get_package_path(store_id)
            if not store_path:
                continue
            pkg_bin = os.path.join(store_path, "bin")
            if os.path.isdir(pkg_bin):
                for exe in os.listdir(pkg_bin):
                    src = os.path.join(pkg_bin, exe)
                    dst = os.path.join(bin_dir, exe)
                    os.symlink(src, dst)
        current_link = os.path.join(PROFILE_DIR, self.name + "-current")
        if os.path.exists(current_link):
            os.remove(current_link)
        os.symlink(os.path.join(self.dir, f"gen-{generation}"), current_link)
        logger(f"Switched profile {self.name} to generation {generation}")

    def add_generation(self, store_ids):
        gen, _ = self.current_generation()
        new_gen = gen + 1
        self.db.add_profile_generation(self.name, new_gen, store_ids)
        gen_dir = os.path.join(self.dir, f"gen-{new_gen}")
        ensure_dir(gen_dir)
        with open(os.path.join(gen_dir, "manifest.json"), "w") as f:
            json.dump(store_ids, f)
        self.switch_to_generation(new_gen)
        return new_gen


# ==================== Transaction ====================
class Transaction:
    def __init__(self, profile_name="default", use_sandbox=True, cache_url=None):
        self.store = Store()
        self.builder = Builder(self.store, use_sandbox=use_sandbox)
        self.fetcher = SourceFetcher(SOURCE_CACHE)
        self.repo_mgr = RepoManager()
        self.profile = Profile(profile_name)
        self.cache = BinaryCache(cache_url)

    def install(self, package_specs):
        # Parse specs
        specs = []
        for spec in package_specs:
            name = spec.split(">")[0].split("<")[0].split("=")[0].strip()
            constraint = spec[len(name) :].strip()
            specs.append((name, constraint))

        recipes_by_name = self.repo_mgr.index_recipes_by_name()
        resolver = Resolver(recipes_by_name)
        all_recipes = []
        seen_names = set()
        for name, constraint in specs:
            recipes = resolver.resolve(name, constraint)
            for r in recipes:
                if r.name not in seen_names:
                    seen_names.add(r.name)
                    all_recipes.append(r)

        built_store_ids = []
        built_store_paths = {}
        for recipe in all_recipes:
            # Find dependencies already built
            dep_ids = []
            dep_paths = []
            for dep_name in recipe.dependencies:
                dep_name_clean = dep_name.split(">")[0].split("<")[0].split("=")[0].strip()
                # find the recipe in all_recipes that matches dep_name_clean
                dep_recipe = next((r for r in all_recipes if r.name == dep_name_clean), None)
                if dep_recipe:
                    idx = all_recipes.index(dep_recipe)
                    dep_ids.append(built_store_ids[idx])
                    dep_paths.append(built_store_paths[built_store_ids[idx]])

            source_dir, source_hash = self.fetcher.fetch(recipe)
            store_hash = self.store.compute_derivation_hash(recipe, source_hash, dep_ids)

            existing_path = self.store.get_package_path(store_hash)
            if existing_path:
                logger(f"Package {recipe.name}-{recipe.version} already in store")
                store_path = existing_path
            else:
                cache_path = os.path.join(
                    self.store.root, store_hash + "-" + recipe.name + "-" + recipe.version
                )
                if self.cache.fetch(store_hash, cache_path):
                    store_path = cache_path
                    self.store.db.add_store_package(
                        store_hash, recipe.name, recipe.version, store_path
                    )
                else:
                    logger(f"Building {recipe.name}-{recipe.version}")
                    built_dir = self.builder.build(recipe, source_dir, dep_paths)
                    store_path = self.store.add_package(recipe, source_hash, dep_ids, built_dir)

            store_id = os.path.basename(store_path).split("-")[0]
            built_store_ids.append(store_id)
            built_store_paths[store_id] = store_path

        current_gen, current_pkgs = self.profile.current_generation()
        new_pkgs = list(set(current_pkgs) | set(built_store_ids))
        self.profile.add_generation(new_pkgs)
        logger("Installation complete. New profile generation created.")

    def uninstall(self, package_names):
        current_gen, current_pkgs = self.profile.current_generation()
        store = self.store
        to_remove = set()
        for store_id in current_pkgs:
            path = store.get_package_path(store_id)
            if path:
                base = os.path.basename(path)
                parts = base.split("-", 2)
                if len(parts) == 3:
                    _, name, version = parts
                    if name in package_names:
                        to_remove.add(store_id)
        new_pkgs = [p for p in current_pkgs if p not in to_remove]
        if new_pkgs != current_pkgs:
            self.profile.add_generation(new_pkgs)
            logger(f"Uninstalled {', '.join(package_names)}. New generation created.")
        else:
            logger("No packages removed.")

    def upgrade(self, package_names):
        # For simplicity, just reinstall the named packages (will create new generation)
        # This may leave old versions but that's okay.
        if not package_names:
            # upgrade all
            current_gen, current_pkgs = self.profile.current_generation()
            store = self.store
            names = set()
            for store_id in current_pkgs:
                path = store.get_package_path(store_id)
                if path:
                    base = os.path.basename(path)
                    parts = base.split("-", 2)
                    if len(parts) == 3:
                        _, name, version = parts
                        names.add(name)
            package_names = list(names)
        self.install(package_names)


# ==================== CLI ====================
def main():
    parser = argparse.ArgumentParser(description="pygr - Python GitHub Repository package manager")
    parser.add_argument(
        "--sandbox",
        action="store_true",
        default=True,
        help="Enable build sandboxing (requires firejail)",
    )
    parser.add_argument(
        "--no-sandbox", dest="sandbox", action="store_false", help="Disable sandboxing"
    )
    parser.add_argument("--cache", help="Binary cache URL (env: PYGR_CACHE_URL)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # repo-add
    repo_add = subparsers.add_parser("repo-add", help="Add a recipe repository")
    repo_add.add_argument("name")
    repo_add.add_argument("url")

    # repo-list
    subparsers.add_parser("repo-list", help="List added repositories")

    # install
    install = subparsers.add_parser("install", help="Install packages")
    install.add_argument("packages", nargs="+")

    # list
    subparsers.add_parser("list", help="List installed packages")

    # uninstall
    uninstall = subparsers.add_parser("uninstall", help="Remove packages")
    uninstall.add_argument("packages", nargs="+")

    # upgrade
    upgrade = subparsers.add_parser("upgrade", help="Upgrade packages")
    upgrade.add_argument("packages", nargs="*")

    # rollback
    subparsers.add_parser("rollback", help="Rollback to previous generation")

    args = parser.parse_args()
    cache_url = args.cache or os.environ.get("PYGR_CACHE_URL")

    if args.command == "repo-add":
        mgr = RepoManager()
        mgr.add_repo(args.name, args.url)
        print(f"Repository {args.name} added.")
    elif args.command == "repo-list":
        db = Database()
        repos = db.list_repos()
        db.close()
        for name, url in repos:
            print(f"{name}: {url}")
    elif args.command == "install":
        trans = Transaction(use_sandbox=args.sandbox, cache_url=cache_url)
        trans.install(args.packages)
    elif args.command == "list":
        profile = Profile()
        gen, pkgs = profile.current_generation()
        if not pkgs:
            print("No packages installed.")
            return
        store = Store()
        print(f"Profile generation {gen}:")
        for store_id in pkgs:
            path = store.get_package_path(store_id)
            if path:
                name_ver = os.path.basename(path).split("-", 1)[1]
                print(f"  {name_ver}")
    elif args.command == "uninstall":
        trans = Transaction(use_sandbox=args.sandbox)
        trans.uninstall(args.packages)
    elif args.command == "upgrade":
        trans = Transaction(use_sandbox=args.sandbox, cache_url=cache_url)
        trans.upgrade(args.packages)
    elif args.command == "rollback":
        profile = Profile()
        gen, _ = profile.current_generation()
        if gen <= 1:
            print("No previous generation.")
            return
        profile.switch_to_generation(gen - 1)
        print(f"Rolled back to generation {gen - 1}")


if __name__ == "__main__":
    main()
