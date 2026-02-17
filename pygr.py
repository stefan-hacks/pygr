#!/usr/bin/env python3
"""
pygr - Python GitHub Repository package manager (pdrx-style imperative + declarative)

Use imperatively: search GitHub, install/remove packages from GitHub. Every action
updates a declarative config (packages.conf) so you can restore with pygr apply.

- Search: pygr search ripgrep  (GitHub API)
- Install: pygr install owner/repo  or  pygr install recipe_name  (from recipe repos)
- Remove: pygr remove name  (uninstalls and removes from config)
- Sync: pygr sync  (write current profile state to declarative config)
- Apply: pygr apply  (install everything in declarative config)
- Backup/rollback, export/import, status, generations (like pdrx)
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
from typing import Any, Dict, List, Optional, Tuple
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
CONFIG_DIR = os.path.join(PYGR_ROOT, "config")
PACKAGES_CONF = os.path.join(CONFIG_DIR, "packages.conf")
BACKUPS_DIR = os.path.join(PYGR_ROOT, "backups")

# Ensure directories exist
os.makedirs(STORE_ROOT, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)
os.makedirs(REPO_CACHE, exist_ok=True)
os.makedirs(SOURCE_CACHE, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)


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


# ==================== Distro package manager (prefer official repo) ====================
def _detect_distro() -> Optional[Tuple[str, str, str, str]]:
    """Return (pm_key, install_cmd, search_cmd, remove_cmd) or None. pm_key e.g. apt, dnf, pacman, zypper, apk."""
    os_release = "/etc/os-release"
    if not os.path.isfile(os_release):
        return None
    env: Dict[str, str] = {}
    with open(os_release) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v.strip('"').strip("'")
    id_like = (env.get("ID_LIKE") or "").split()
    id_ = env.get("ID", "").lower()
    if id_ in ("debian", "ubuntu", "linuxmint", "pop") or "debian" in id_like:
        return ("apt", "sudo apt-get install -y", "apt-cache search --names-only ^", "sudo apt-get remove -y")
    if id_ in ("fedora", "rhel", "centos", "rocky", "alma") or "fedora" in id_like or "rhel" in id_like:
        return ("dnf", "sudo dnf install -y", "dnf list available", "sudo dnf remove -y")
    if id_ in ("arch", "manjaro") or "arch" in id_like:
        return ("pacman", "sudo pacman -S --noconfirm", "pacman -Ss", "sudo pacman -R --noconfirm")
    if id_ in ("opensuse-leap", "opensuse-tumbleweed", "sles") or "suse" in id_like:
        return ("zypper", "sudo zypper install -y", "zypper search", "sudo zypper remove -y")
    if id_ == "alpine":
        return ("apk", "sudo apk add", "apk search", "sudo apk del")
    return None


def distro_package_available(pm_key: str, name: str) -> bool:
    """Check if a package is available in the distro (without installing)."""
    try:
        if pm_key == "apt":
            r = subprocess.run(
                f"apt-cache show {name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.returncode == 0 and bool(r.stdout.strip())
        if pm_key == "dnf":
            r = subprocess.run(
                f"dnf list available {name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return r.returncode == 0 and name in (r.stdout or "")
        if pm_key == "pacman":
            r = subprocess.run(
                f"pacman -Ss ^{name}$",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.returncode == 0 and bool((r.stdout or "").strip())
        if pm_key == "zypper":
            r = subprocess.run(
                f"zypper search -n {name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return r.returncode == 0 and name in (r.stdout or "")
        if pm_key == "apk":
            r = subprocess.run(
                f"apk search -e {name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.returncode == 0 and name in (r.stdout or "")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False


def distro_install(pm_key: str, name: str) -> bool:
    """Install package via distro PM. Returns True on success."""
    info = _detect_distro()
    if not info or info[0] != pm_key:
        return False
    _pm, install_cmd, _s, _r = info
    try:
        subprocess.run(f"{install_cmd} {name}", shell=True, check=True, timeout=300)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def distro_remove(pm_key: str, name: str) -> bool:
    """Remove package via distro PM. Returns True on success."""
    info = _detect_distro()
    if not info or info[0] != pm_key:
        return False
    _pm, _i, _s, remove_cmd = info
    try:
        subprocess.run(f"{remove_cmd} {name}", shell=True, check=True, timeout=120)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _install_simple_name_from_github(
    name: str, use_sandbox: bool = True, cache_url: Optional[str] = None
) -> None:
    """Search GitHub for name and install the first (best) result."""
    items = github_search(name, per_page=5)
    if not items:
        raise SystemExit(f"No GitHub repo found for '{name}'. Try: pygr search {name}")
    best = items[0]
    full_name = best.get("full_name", "")
    if "/" in full_name:
        install_from_github(full_name, use_sandbox=use_sandbox, cache_url=cache_url)
    else:
        raise SystemExit(f"No GitHub repo found for '{name}'.")


def try_install_from_distro(name: str) -> Optional[str]:
    """
    If current distro has a package for name, install it and return spec (e.g. distro:apt:name).
    Otherwise return None.
    """
    info = _detect_distro()
    if not info:
        return None
    pm_key, _i, _s, _r = info
    if not distro_package_available(pm_key, name):
        return None
    logger(f"Using {pm_key} package for {name} (compatible with your distribution)")
    if distro_install(pm_key, name):
        return f"distro:{pm_key}:{name}"
    return None


# ==================== Declarative Config (pdrx-style) ====================
# packages.conf format: one line per package. Lines are either:
#   distro:pm:name            (installed via system package manager)
#   github:owner/repo@ref     (install from GitHub; ref = branch, tag, or commit)
#   recipe:name@version       (install from recipe in added repos)
# Comments and blank lines are preserved on read; comments written at head.


def _parse_packages_line(line: str) -> Optional[Tuple[str, str]]:
    """Return (kind:spec, display_name) or None for comment/blank."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("distro:"):
        # distro:apt:ripgrep -> display name ripgrep
        parts = line[7:].strip().split(":", 1)
        if len(parts) == 2:
            return (line, parts[1].strip())
        return (line, line[7:].strip())
    if line.startswith("github:"):
        spec = line[7:].strip()
        if "@" in spec:
            repo_part = spec.split("@")[0]
        else:
            repo_part = spec
        name = repo_part.split("/")[-1] if "/" in repo_part else repo_part
        return (line, name)
    if line.startswith("recipe:"):
        spec = line[7:].strip()
        name = spec.split("@")[0].strip() if "@" in spec else spec.split()[0]
        return (line, name)
    return None


class DeclarativeConfig:
    """Read/write declarative packages.conf (updated on install/remove/sync)."""

    def __init__(self, path: str = PACKAGES_CONF):
        self.path = path

    def read_entries(self) -> List[Tuple[str, str]]:
        """Return list of (raw_line, display_name)."""
        if not os.path.isfile(self.path):
            return []
        entries = []
        with open(self.path) as f:
            for line in f:
                parsed = _parse_packages_line(line)
                if parsed:
                    entries.append(parsed)
        return entries

    def read_specs(self) -> List[str]:
        """Return list of spec strings (github:... or recipe:...)."""
        return [e[0] for e in self.read_entries()]

    def add_entry(self, spec: str) -> None:
        """Append one line to packages.conf. spec = 'github:owner/repo@ref' or 'recipe:name@ver'."""
        ensure_dir(os.path.dirname(self.path))
        header = []
        if os.path.isfile(self.path):
            with open(self.path) as f:
                for line in f:
                    if line.strip().startswith("#") or not line.strip():
                        header.append(line.rstrip("\n"))
                    else:
                        break
        existing = set(self.read_specs())
        if spec in existing:
            return
        with open(self.path, "a") as f:
            if not header and os.path.isfile(self.path) and os.path.getsize(self.path) == 0:
                f.write(
                    "# pygr declarative packages\n"
                    "# Format: distro:pm:name | github:owner/repo@ref | recipe:name@version\n"
                    "# ADD: pygr install <name> (tries distro then recipe then GitHub)\n"
                    "# REMOVE: pygr remove <name>\n"
                    "# RESTORE: pygr apply\n\n"
                )
            f.write(spec + "\n")

    def remove_by_name(self, display_name: str) -> Optional[str]:
        """Remove first entry whose display name matches. Return the removed spec line or None."""
        if not os.path.isfile(self.path):
            return None
        with open(self.path) as f:
            lines = f.readlines()
        new_lines = []
        removed_spec = None
        for line in lines:
            parsed = _parse_packages_line(line)
            if parsed and parsed[1] == display_name and removed_spec is None:
                removed_spec = parsed[0]
                continue
            new_lines.append(line)
        if removed_spec is not None:
            with open(self.path, "w") as f:
                f.writelines(new_lines)
        return removed_spec

    def write_entries(self, specs: List[str]) -> None:
        """Overwrite packages.conf with these spec lines."""
        ensure_dir(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write(
                "# pygr declarative packages\n"
                "# Format: distro:pm:name | github:owner/repo@ref | recipe:name@version\n"
                "# RESTORE: pygr apply\n\n"
            )
            for s in specs:
                f.write(s + "\n")


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
                spec TEXT DEFAULT '',
                install_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            c.execute("ALTER TABLE store_packages ADD COLUMN spec TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column exists
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

    def add_store_package(self, store_id, name, version, store_path, spec=""):
        c = self.conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO store_packages (id, name, version, store_path, spec) VALUES (?,?,?,?,?)",
            (store_id, name, version, store_path, spec),
        )
        self.conn.commit()

    def get_store_package(self, store_id):
        c = self.conn.cursor()
        c.execute("SELECT id, name, version, store_path, COALESCE(spec,'') FROM store_packages WHERE id=?", (store_id,))
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


# ==================== GitHub Search ====================
def github_search(query: str, per_page: int = 10) -> List[Dict[str, Any]]:
    """Search GitHub repositories. Returns list of dicts with full_name, html_url, description, etc."""
    url = "https://api.github.com/search/repositories"
    params = {"q": query, "per_page": per_page, "sort": "stars"}
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("items", [])
    except requests.RequestException as e:
        logger(f"GitHub search failed: {e}", "WARNING")
        return []


# ==================== Ad-hoc install from GitHub ====================
def _resolve_ref(repo_url: str, ref: str) -> str:
    """Resolve branch/tag to commit hash."""
    if len(ref) == 40 and ref.isalnum():
        return ref
    out = run_cmd(f"git ls-remote {repo_url} {ref}", capture_output=True)
    commit = (out.stdout or "").split()[0] if out.stdout else None
    if not commit:
        raise Exception(f"Could not resolve ref {ref} for {repo_url}")
    return commit


def _adhoc_build_and_install(
    source_dir: str,
    store_path: str,
    repo_name: str,
    ref: str,
    use_sandbox: bool,
) -> None:
    """Detect build system in source_dir, build, and copy artifacts to store_path.
    Supports: Rust (Cargo), Go, Node.js, Python, CMake, Meson, Makefile, Ruby, Gradle, Maven, Just.
    """
    ensure_dir(store_path)
    bin_dir = os.path.join(store_path, "bin")
    ensure_dir(bin_dir)
    env = os.environ.copy()

    # --- Rust ---
    if os.path.isfile(os.path.join(source_dir, "Cargo.toml")):
        run_cmd("cargo build --release", cwd=source_dir, env=env, check=True)
        release = os.path.join(source_dir, "target", "release")
        if os.path.isdir(release):
            for exe in os.listdir(release):
                p = os.path.join(release, exe)
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    shutil.copy2(p, os.path.join(bin_dir, exe))
        return

    # --- Go ---
    if os.path.isfile(os.path.join(source_dir, "go.mod")):
        run_cmd(f"go build -o {os.path.join(bin_dir, repo_name)} .", cwd=source_dir, env=env, check=True)
        return

    # --- Node.js (before Python: some repos have both) ---

    if os.path.isfile(os.path.join(source_dir, "package.json")):
        # Node.js: npm install, copy project to store, create bin wrappers from package.json "bin"
        run_cmd("npm install --production", cwd=source_dir, env=env, check=True)
        # Copy full project into store_path (package root = store_path)
        for item in os.listdir(source_dir):
            src = os.path.join(source_dir, item)
            dst = os.path.join(store_path, item)
            if item == "bin":
                continue
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        pkg_path = os.path.join(store_path, "package.json")
        with open(pkg_path) as f:
            pkg = json.load(f)
        bin_map = pkg.get("bin")
        if isinstance(bin_map, str):
            bin_map = {pkg.get("name", repo_name): bin_map}
        if not isinstance(bin_map, dict):
            bin_map = {}
        for cmd_name, rel_script in bin_map.items():
            if not rel_script:
                continue
            script_path = os.path.normpath(os.path.join(store_path, rel_script))
            if not os.path.isfile(script_path):
                continue
            rel_from_bin = os.path.relpath(script_path, bin_dir)
            wrapper = os.path.join(bin_dir, cmd_name)
            with open(wrapper, "w") as w:
                w.write("#!/bin/sh\n")
                w.write('dir="$(cd "$(dirname "$0")" && pwd)"\n')
                w.write(f'exec node "$dir/{rel_from_bin}" "$@"\n')
            os.chmod(wrapper, 0o755)
        if bin_map:
            return

    # --- CMake ---
    if os.path.isfile(os.path.join(source_dir, "CMakeLists.txt")):
        build_d = os.path.join(source_dir, "build")
        ensure_dir(build_d)
        run_cmd("cmake -DCMAKE_INSTALL_PREFIX=../install-root -DCMAKE_BUILD_TYPE=Release ..", cwd=build_d, env=env, check=True)
        run_cmd("cmake --build . --target install", cwd=build_d, env=env, check=True)
        prefix = os.path.join(source_dir, "install-root")
        for sub in ("bin", "libexec", "lib"):
            src_bin = os.path.join(prefix, sub)
            if os.path.isdir(src_bin):
                for exe in os.listdir(src_bin):
                    p = os.path.join(src_bin, exe)
                    if os.path.isfile(p) and os.access(p, os.X_OK):
                        shutil.copy2(p, os.path.join(bin_dir, exe))
        return

    # --- Meson ---
    if os.path.isfile(os.path.join(source_dir, "meson.build")):
        build_d = os.path.join(source_dir, "build")
        ensure_dir(build_d)
        run_cmd("meson setup build -Dprefix=../install-root -Dbuildtype=release", cwd=source_dir, env=env, check=True)
        run_cmd("meson compile -C build", cwd=source_dir, env=env, check=True)
        run_cmd("meson install -C build", cwd=source_dir, env=env, check=True)
        prefix = os.path.join(source_dir, "install-root")
        for sub in ("bin", "libexec"):
            src_bin = os.path.join(prefix, sub)
            if os.path.isdir(src_bin):
                for exe in os.listdir(src_bin):
                    p = os.path.join(src_bin, exe)
                    if os.path.isfile(p) and os.access(p, os.X_OK):
                        shutil.copy2(p, os.path.join(bin_dir, exe))
        return

    # --- Makefile ---
    if os.path.isfile(os.path.join(source_dir, "Makefile")):
        prefix = os.path.join(source_dir, "install-root")
        ensure_dir(prefix)
        run_cmd(f"make PREFIX={prefix} install", cwd=source_dir, env=env, check=True)
        src_bin = os.path.join(prefix, "bin")
        if os.path.isdir(src_bin):
            for exe in os.listdir(src_bin):
                shutil.copy2(os.path.join(src_bin, exe), os.path.join(bin_dir, exe))
        return

    # --- Ruby (Gemfile) ---
    if os.path.isfile(os.path.join(source_dir, "Gemfile")):
        run_cmd("bundle config set --local path vendor/bundle", cwd=source_dir, env=env, check=True)
        run_cmd("bundle install", cwd=source_dir, env=env, check=True)
        exe_dir = os.path.join(source_dir, "exe")
        if os.path.isdir(exe_dir):
            for exe in os.listdir(exe_dir):
                p = os.path.join(exe_dir, exe)
                if os.path.isfile(p):
                    shutil.copy2(p, os.path.join(bin_dir, exe))
                    os.chmod(os.path.join(bin_dir, exe), 0o755)
        return

    # --- Gradle (Java/Kotlin) ---
    if os.path.isfile(os.path.join(source_dir, "build.gradle")) or os.path.isfile(os.path.join(source_dir, "build.gradle.kts")):
        run_cmd("./gradlew installDist", cwd=source_dir, env=env, check=True)
        for d in ("build/install", "build/install/main"):
            inst = os.path.join(source_dir, d, "bin")
            if os.path.isdir(inst):
                for exe in os.listdir(inst):
                    p = os.path.join(inst, exe)
                    if os.path.isfile(p) and os.access(p, os.X_OK):
                        shutil.copy2(p, os.path.join(bin_dir, exe))
                return

    # --- Maven (Java) ---
    if os.path.isfile(os.path.join(source_dir, "pom.xml")):
        run_cmd("mvn -q package -DskipTests", cwd=source_dir, env=env, check=True)
        jar_path = None
        for root, _dirs, files in os.walk(os.path.join(source_dir, "target")):
            for f in files:
                if f.endswith(".jar") and "original" not in root and "-sources" not in f:
                    p = os.path.join(root, f)
                    if "-with-dependencies" in f:
                        jar_path = p
                        break
                    if not jar_path:
                        jar_path = p
            if jar_path:
                break
        if jar_path:
            ensure_dir(os.path.join(store_path, "lib"))
            jar_name = os.path.basename(jar_path)
            shutil.copy2(jar_path, os.path.join(store_path, "lib", jar_name))
            wrapper = os.path.join(bin_dir, repo_name)
            with open(wrapper, "w") as w:
                w.write("#!/bin/sh\nexec java -jar \"$(dirname \"$0\")/../lib/" + jar_name + "\" \"$@\"\n")
            os.chmod(wrapper, 0o755)
        return

    # --- Just (justfile) ---
    if os.path.isfile(os.path.join(source_dir, "justfile")) or os.path.isfile(os.path.join(source_dir, "Justfile")):
        run_cmd("just --list", cwd=source_dir, env=env, check=True)
        run_cmd("just build", cwd=source_dir, env=env, check=False)
        for sub in ("target/release", "build", "bin", "."):
            d = os.path.join(source_dir, sub)
            if os.path.isdir(d):
                for f in os.listdir(d):
                    p = os.path.join(d, f)
                    if os.path.isfile(p) and os.access(p, os.X_OK) and not f.startswith("."):
                        shutil.copy2(p, os.path.join(bin_dir, f))
                        return
        logger("Just build did not produce an executable in expected locations", "WARNING")

    # --- Python ---
    if os.path.isfile(os.path.join(source_dir, "setup.py")) or os.path.isfile(
        os.path.join(source_dir, "pyproject.toml")
    ):
        run_cmd(
            f"pip install --target {os.path.join(store_path, 'lib')} .",
            cwd=source_dir,
            env=env,
            check=True,
        )
        # Create bin wrappers if any console_scripts
        lib = os.path.join(store_path, "lib")
        for root, _dirs, files in os.walk(lib):
            for f in files:
                if f.endswith(".py") and root == os.path.join(lib, "bin"):
                    shutil.copy2(os.path.join(root, f), os.path.join(bin_dir, f))
        return

    logger("No known build system detected (Cargo, Go, Node, CMake, Meson, Make, Ruby, Gradle, Maven, Just, Python); copying executables from root", "WARNING")
    # Fallback: copy any executable in root
    for f in os.listdir(source_dir):
        p = os.path.join(source_dir, f)
        if os.path.isfile(p) and os.access(p, os.X_OK) and not f.startswith("."):
            shutil.copy2(p, os.path.join(bin_dir, f))


def install_from_github(
    owner_repo: str,
    ref: str = "HEAD",
    use_sandbox: bool = True,
    cache_url: Optional[str] = None,
) -> str:
    """
    Install from GitHub owner/repo@ref (ad-hoc: clone + detect build). Returns store_id.
    Updates store, profile, and declarative config.
    """
    if "/" not in owner_repo:
        raise ValueError("Use owner/repo (e.g. BurntSushi/ripgrep)")
    owner, repo = owner_repo.split("/", 1)
    repo = repo.split("@")[0].strip()
    if "@" in owner_repo:
        ref = owner_repo.split("@")[-1].strip()
    repo_url = f"https://github.com/{owner}/{repo}.git"
    commit = _resolve_ref(repo_url, ref)

    fetcher = SourceFetcher(SOURCE_CACHE)
    cache_key = f"{owner}_{repo}_{commit}"
    cache_path = os.path.join(SOURCE_CACHE, cache_key)
    if not os.path.exists(cache_path):
        with tempfile.TemporaryDirectory() as tmpdir:
            r = git.Repo.clone_from(repo_url, tmpdir, depth=1, no_checkout=True)
            r.git.fetch("--depth=1", "origin", commit)
            r.git.checkout(commit)
            shutil.copytree(tmpdir, cache_path)

    store = Store()
    store_hash = hashlib.sha256(f"github:{owner}/{repo}@{commit}".encode()).hexdigest()[:16]
    store_id = store_hash
    store_path = os.path.join(store.root, f"{store_id}-{repo}-{ref}")
    if os.path.exists(store_path):
        logger(f"Already installed: {repo}")
    else:
        _adhoc_build_and_install(cache_path, store_path, repo, ref, use_sandbox)
        spec = f"github:{owner}/{repo}@{commit}"
        store.db.add_store_package(store_id, repo, ref, store_path, spec)

    profile = Profile()
    gen, pkgs = profile.current_generation()
    if store_id not in pkgs:
        new_pkgs = list(pkgs) + [store_id]
        profile.add_generation(new_pkgs)
    spec = f"github:{owner}/{repo}@{commit}"
    DeclarativeConfig().add_entry(spec)
    logger(f"Installed {repo} (github:{owner}/{repo}@{commit})")
    _print_path_hint()
    return store_id


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

    def add_package(self, recipe, source_hash, dep_hashes, build_output_dir, spec=None):
        store_hash = self.compute_derivation_hash(recipe, source_hash, dep_hashes)
        store_path = os.path.join(self.root, f"{store_hash}-{recipe.name}-{recipe.version}")
        if os.path.exists(store_path):
            logger(f"Package already exists in store: {store_path}")
            return store_path
        if spec is None:
            spec = f"recipe:{recipe.name}@{recipe.version}"
        logger(f"Installing to store: {store_path}")
        shutil.copytree(build_output_dir, store_path)
        self.db.add_store_package(store_hash, recipe.name, recipe.version, store_path, spec)
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
                        store_hash,
                        recipe.name,
                        recipe.version,
                        store_path,
                        f"recipe:{recipe.name}@{recipe.version}",
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
        cfg = DeclarativeConfig()
        for r in all_recipes:
            cfg.add_entry(f"recipe:{r.name}@{r.version}")
        logger("Installation complete. New profile generation created.")
        _print_path_hint()

    def uninstall(self, package_names):
        cfg = DeclarativeConfig()
        for name in package_names:
            removed_spec = cfg.remove_by_name(name)
            if removed_spec and removed_spec.startswith("distro:"):
                parts = removed_spec[7:].strip().split(":", 1)
                if len(parts) == 2:
                    pm_key, pkg_name = parts[0].strip(), parts[1].strip()
                    distro_remove(pm_key, pkg_name)
                    logger(f"Removed {pkg_name} via {pm_key}")
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


def _profile_bin_dir(profile_name: str = "default") -> str:
    """Return the profile's bin directory where executables are symlinked."""
    return os.path.join(PROFILE_DIR, profile_name, "bin")


def _print_path_hint() -> None:
    """Print how to add installed tools to PATH."""
    bin_dir = _profile_bin_dir()
    if not os.path.isdir(bin_dir):
        return
    print()
    print("To use installed tools, add the profile bin to your PATH:")
    print(f"  export PATH=\"{bin_dir}:$PATH\"")
    print("Or run:  eval $(pygr path)")
    print("Add the above to ~/.bashrc or ~/.profile to make it permanent.")


# ==================== Sync / Apply / Status / Backup (pdrx-style) ====================
def cmd_sync() -> None:
    """Write current profile state to declarative packages.conf (preserves distro: entries)."""
    cfg = DeclarativeConfig()
    existing = cfg.read_entries()
    distro_specs = [e[0] for e in existing if e[0].startswith("distro:")]
    profile = Profile()
    gen, store_ids = profile.current_generation()
    store = Store()
    store_specs = []
    for sid in store_ids:
        row = store.db.get_store_package(sid)
        if row:
            spec = row[4] if len(row) > 4 else ""
            if not spec:
                spec = f"recipe:{row[1]}@{row[2]}"
            store_specs.append(spec)
    cfg.write_entries(distro_specs + store_specs)
    logger(f"Synced generation {gen} ({len(distro_specs)} distro + {len(store_specs)} store) to {PACKAGES_CONF}")


def cmd_apply(use_sandbox: bool = True, cache_url: Optional[str] = None) -> None:
    """Install all packages from declarative config."""
    cfg = DeclarativeConfig()
    specs = cfg.read_specs()
    if not specs:
        logger("No packages in config. Add with pygr install or edit packages.conf.")
        return
    trans = Transaction(use_sandbox=use_sandbox, cache_url=cache_url)
    distro_specs = []
    github_specs = []
    recipe_specs = []
    for s in specs:
        if s.startswith("distro:"):
            distro_specs.append(s)
        elif s.startswith("github:"):
            github_specs.append(s)
        elif s.startswith("recipe:"):
            recipe_specs.append(s)
    for spec in distro_specs:
        # distro:apt:ripgrep
        parts = spec[7:].strip().split(":", 1)
        if len(parts) == 2:
            _pm, name = parts
            if distro_install(_pm.strip(), name.strip()):
                logger(f"Installed {name} via {_pm}")
    for spec in github_specs:
        part = spec[7:].strip()
        if "@" in part:
            repo_ref = part.split("@", 1)
            owner_repo = repo_ref[0].strip()
            ref = repo_ref[1].strip()
            install_from_github(owner_repo, ref=ref, use_sandbox=use_sandbox, cache_url=cache_url)
        else:
            install_from_github(part, use_sandbox=use_sandbox, cache_url=cache_url)
    if recipe_specs:
        specs_for_install = []
        for s in recipe_specs:
            part = s[7:].strip()
            if "@" in part:
                name, ver = part.split("@", 1)
                specs_for_install.append(f"{name.strip()}=={ver.strip()}")
            else:
                specs_for_install.append(part)
        trans.install(specs_for_install)


def cmd_status() -> None:
    """Show config path, package count, backups."""
    cfg = DeclarativeConfig()
    entries = cfg.read_entries()
    profile = Profile()
    gen, pkgs = profile.current_generation()
    backups = sorted([d for d in os.listdir(BACKUPS_DIR) if os.path.isdir(os.path.join(BACKUPS_DIR, d))])
    print(f"Config:     {PACKAGES_CONF}")
    print(f"Packages:   {len(entries)} in config  |  {len(pkgs)} in current profile (gen {gen})")
    print(f"Backups:    {len(backups)}")


def cmd_backup(label: str = "") -> str:
    """Create timestamped backup of config. Returns path."""
    from datetime import datetime

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    name = f"{ts}_manual" if not label else f"{ts}_{label}"
    dest = os.path.join(BACKUPS_DIR, name)
    ensure_dir(dest)
    for item in ["config"]:
        src = os.path.join(PYGR_ROOT, item)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, item), dirs_exist_ok=True)
    logger(f"Backup: {dest}")
    return dest


def cmd_generations() -> None:
    """List profile generations and backup dirs."""
    profile = Profile()
    gen, _ = profile.current_generation()
    c = profile.db.conn.cursor()
    c.execute("SELECT generation FROM profiles WHERE name=? ORDER BY generation", (profile.name,))
    gens = [row[0] for row in c.fetchall()]
    print("Profile generations (current = *):")
    for g in gens:
        print(f"  {g}" + (" *" if g == gen else ""))
    backups = sorted([d for d in os.listdir(BACKUPS_DIR) if os.path.isdir(os.path.join(BACKUPS_DIR, d))])
    if backups:
        print("Backups:")
        for b in backups:
            print(f"  {b}")


def cmd_export(path: str = "") -> None:
    """Export config to tarball."""
    from datetime import datetime

    out = path or f"pygr-export-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(CONFIG_DIR, arcname="config")
    logger(f"Exported to {out}")


def cmd_import(archive: str) -> None:
    """Import config from tarball."""
    with tarfile.open(archive, "r:*") as tar:
        tar.extractall(path=PYGR_ROOT)
    logger(f"Imported from {archive}. Run pygr apply to install.")


# ==================== CLI ====================
def main():
    parser = argparse.ArgumentParser(
        description="pygr - Python GitHub Repository package manager (imperative + declarative)"
    )
    parser.add_argument(
        "-c", "--config", dest="config_dir", metavar="DIR", help="Use DIR as PYGR_ROOT"
    )
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

    # search (GitHub)
    search_p = subparsers.add_parser("search", help="Search GitHub for repositories")
    search_p.add_argument("query", help="Search query (e.g. ripgrep, cowsay)")
    search_p.add_argument("-n", "--num", type=int, default=10, help="Max results (default 10)")

    # install (name -> try distro, then recipe, then GitHub; or owner/repo -> GitHub)
    install = subparsers.add_parser(
        "install",
        help="Install: try distro package first, then recipe, then build from GitHub",
    )
    install.add_argument(
        "packages",
        nargs="+",
        help="Package name(s) or owner/repo (e.g. ripgrep or BurntSushi/ripgrep)",
    )
    install.add_argument(
        "--from-github",
        action="store_true",
        help="Skip distro/recipe; install from GitHub only (by name search or owner/repo)",
    )

    # list
    subparsers.add_parser("list", help="List installed packages")

    # path (print export for profile bin)
    subparsers.add_parser(
        "path",
        help="Print shell export to add profile bin to PATH (use: eval $(pygr path))",
    )

    # uninstall
    uninstall = subparsers.add_parser("uninstall", help="Remove packages (updates declarative config)")
    uninstall.add_argument("packages", nargs="+")

    # sync / apply / status / backup / generations / export / import
    subparsers.add_parser("sync", help="Write current profile state to declarative config")
    subparsers.add_parser("apply", help="Install all packages from declarative config")
    subparsers.add_parser("status", help="Show config path, package count, backups")
    backup_p = subparsers.add_parser("backup", help="Create timestamped backup of config")
    backup_p.add_argument("label", nargs="?", default="", help="Optional backup label")
    subparsers.add_parser("generations", help="List profile generations and backups")
    export_p = subparsers.add_parser("export", help="Export config to tarball")
    export_p.add_argument("file", nargs="?", default="", help="Output path")
    import_p = subparsers.add_parser("import", help="Import config from tarball")
    import_p.add_argument("file", help="Tarball path")

    # upgrade
    upgrade = subparsers.add_parser("upgrade", help="Upgrade packages")
    upgrade.add_argument("packages", nargs="*")

    # rollback
    subparsers.add_parser("rollback", help="Rollback to previous generation")

    args = parser.parse_args()
    if getattr(args, "config_dir", None):
        _root = os.path.abspath(args.config_dir)
        os.environ["PYGR_ROOT"] = _root
        # Update module-level paths so -c takes effect
        global PYGR_ROOT, STORE_ROOT, PROFILE_DIR, REPO_CACHE, DB_PATH, SOURCE_CACHE
        global CONFIG_DIR, PACKAGES_CONF, BACKUPS_DIR
        PYGR_ROOT = _root
        STORE_ROOT = os.path.join(PYGR_ROOT, "store")
        PROFILE_DIR = os.path.join(PYGR_ROOT, "profiles")
        REPO_CACHE = os.path.join(PYGR_ROOT, "repos")
        DB_PATH = os.path.join(PYGR_ROOT, "pygr.db")
        SOURCE_CACHE = os.path.join(STORE_ROOT, "sources")
        CONFIG_DIR = os.path.join(PYGR_ROOT, "config")
        PACKAGES_CONF = os.path.join(CONFIG_DIR, "packages.conf")
        BACKUPS_DIR = os.path.join(PYGR_ROOT, "backups")
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
    elif args.command == "search":
        items = github_search(args.query, per_page=args.num)
        for i, repo in enumerate(items, 1):
            full = repo.get("full_name", "")
            desc = (repo.get("description") or "")[:60]
            url = repo.get("html_url", "")
            print(f"{i}. {full}  {desc}")
            print(f"   {url}")
        if not items:
            print("No results. Try GITHUB_TOKEN for higher rate limit.")
    elif args.command == "install":
        trans = Transaction(use_sandbox=args.sandbox, cache_url=cache_url)
        github_pkgs = [p for p in args.packages if "/" in p.split("@")[0]]
        simple_pkgs = [p for p in args.packages if p not in github_pkgs]
        for p in github_pkgs:
            install_from_github(p, use_sandbox=args.sandbox, cache_url=cache_url)
        for p in simple_pkgs:
            if args.from_github:
                _install_simple_name_from_github(p, use_sandbox=args.sandbox, cache_url=cache_url)
                continue
            spec = try_install_from_distro(p)
            if spec:
                DeclarativeConfig().add_entry(spec)
                continue
            try:
                trans.install([p])
            except Exception as e:
                if "No recipe found" in str(e) or "No version" in str(e):
                    _install_simple_name_from_github(p, use_sandbox=args.sandbox, cache_url=cache_url)
                else:
                    raise
        if args.packages:
            _print_path_hint()
    elif args.command == "list":
        cfg = DeclarativeConfig()
        entries = cfg.read_entries()
        if not entries:
            print("No packages in config.")
            return
        profile = Profile()
        gen, pkgs = profile.current_generation()
        print(f"Packages ({len(entries)} in config, {len(pkgs)} in profile gen {gen}):")
        for spec, display_name in entries:
            kind = " (distro)" if spec.startswith("distro:") else ""
            print(f"  {display_name}{kind}")
    elif args.command == "path":
        bin_dir = _profile_bin_dir()
        print(f"export PATH=\"{bin_dir}:$PATH\"")
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
    elif args.command == "sync":
        cmd_sync()
    elif args.command == "apply":
        cmd_apply(use_sandbox=args.sandbox, cache_url=cache_url)
    elif args.command == "status":
        cmd_status()
    elif args.command == "backup":
        cmd_backup(getattr(args, "label", "") or "")
    elif args.command == "generations":
        cmd_generations()
    elif args.command == "export":
        cmd_export(getattr(args, "file", "") or "")
    elif args.command == "import":
        cmd_import(args.file)


if __name__ == "__main__":
    main()
