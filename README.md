<p align="center">
  <img src="icon_pygr.png" width="192" alt="pygr" />
</p>

# pygr

Install and manage tools from your distro, from recipes, or from GitHub. Uses a declarative config so you can restore your setup with `pygr apply`.

---

## Bootstrap installation

**Recommended:** run the installer from the repo or via curl. This creates a venv and puts `pygr` in `~/.local/bin`.

```bash
# From a clone (uses local pygr.py)
./install-pygr.sh

# From the internet (downloads pygr and install script)
curl -sL https://raw.githubusercontent.com/stefan-hacks/pygr/main/install-pygr.sh | bash
```

Ensure `~/.local/bin` is in your `PATH`. Optional overrides:

```bash
PYGR_VENV=/path/to/venv ./install-pygr.sh    # venv location
PYGR_REPO=https://.../pygr/main ./install-pygr.sh   # custom repo URL for pygr.py
```

---

## How to use pygr

### Options reference (all options at a glance)

**Global options** (must appear before the command):

| Option | Description |
|--------|-------------|
| `-c DIR`, `--config DIR` | Use `DIR` as config root (default: `~/.local/share/pygr`). |
| `--sandbox` | Use firejail for build isolation (default). |
| `--no-sandbox` | Disable sandbox. |
| `--cache URL` | Binary cache base URL (or set `PYGR_CACHE_URL`). |

**Commands and their options:**

| Command | Arguments | Options | Description |
|---------|-----------|---------|-------------|
| `search` | `QUERY` | `-n N`, `--num N` (default: 10) | Search GitHub for repositories. |
| `install` | `PACKAGE [PACKAGE ...]` | `--from-github` | Install by name (distro → recipe → GitHub) or `owner/repo`. |
| `uninstall` | `PACKAGE [PACKAGE ...]` | — | Remove packages and from config. |
| `list` | — | — | List packages in config (distro ones marked). |
| `path` | — | — | Print `export PATH=...` for profile bin. |
| `sync` | — | — | Write current profile to declarative config. |
| `apply` | — | — | Install all packages from config. |
| `status` | — | — | Show config path, package counts, backups. |
| `backup` | `[LABEL]` | — | Create timestamped backup (optional label). |
| `generations` | — | — | List profile generations and backups. |
| `rollback` | — | — | Switch to previous generation. |
| `export` | `[FILE]` | — | Export config to tarball. |
| `import` | `FILE` | — | Import config from tarball. |
| `upgrade` | `[PACKAGE ...]` | — | Upgrade named packages or all. |
| `repo-add` | `NAME` `URL` | — | Add a recipe repository. |
| `repo-list` | — | — | List added repositories. |

**Examples (global options):**

```bash
pygr -c /opt/my-pygr install ripgrep
pygr --no-sandbox install owner/repo
pygr --cache https://cache.example.com/pygr install cowsay
```

---

### Commands and options

#### `pygr search QUERY [-n N]`

Search GitHub for repositories.

- **QUERY** — Search string (e.g. `ripgrep`, `cowsay`).
- **-n, --num N** — Max results (default 10).

```bash
pygr search ripgrep
pygr search cowsay -n 5
```

Set `GITHUB_TOKEN` for higher API rate limits.

---

#### `pygr install PACKAGE [PACKAGE ...] [--from-github]`

Install by name or by `owner/repo`. Updates the declarative config automatically.

**Behavior by argument:**

- **Name only (e.g. `ripgrep`):**  
  1. Try **distro** package (apt/dnf/pacman/zypper/apk).  
  2. Else try **recipe** from repos you added.  
  3. Else **search GitHub** and build from the first result.
- **owner/repo (e.g. `BurntSushi/ripgrep`):** Build from that GitHub repo (no distro/recipe lookup).
- **owner/repo@ref:** Same, at branch/tag/commit (e.g. `owner/repo@v1.0`).

**Options:**

- **--from-github** — For name installs: skip distro and recipe; only search GitHub and build.

**Examples:**

```bash
pygr install ripgrep              # distro → recipe → GitHub
pygr install htop
pygr install --from-github ripgrep
pygr install BurntSushi/ripgrep
pygr install piuccio/cowsay
pygr install owner/repo@v1.0
```

After installing tools built from GitHub/recipes, add the profile bin to your PATH:  
`eval $(pygr path)` (or add that line to `~/.bashrc`).

---

## Distribution

Install pygr’s dependencies with your package manager, then run `pygr.py` (or use the [bootstrap](#bootstrap-installation) which uses a venv and does not need system Python packages).

| Distribution | Install command |
|--------------|-----------------|
| **Debian / Ubuntu** | `sudo apt update && sudo apt install -y python3 python3-pip git firejail python3-yaml python3-git python3-requests python3-packaging` |
| **Fedora / RHEL / CentOS** | `sudo dnf install -y python3 python3-pip git firejail python3-pyyaml python3-GitPython python3-requests python3-packaging` |
| **Arch Linux** | `sudo pacman -S --needed python python-pip git firejail python-yaml python-gitpython python-requests python-packaging` |
| **openSUSE (Tumbleweed / Leap)** | `sudo zypper install -y python3 python3-pip git firejail python3-PyYAML python3-GitPython python3-requests python3-packaging` |
| **Alpine Linux** | `sudo apk add python3 py3-pip git firejail py3-yaml py3-git py3-requests py3-packaging` |

Optional: omit **firejail** if you do not want build sandboxing (use `pygr --no-sandbox` when building).  
If a distro does not package GitPython or others, use the [bootstrap](#bootstrap-installation) or a virtual environment and `pip install -r requirements.txt`.

---

## Other useful info

### Requirements

- Python 3.8+
- Git
- Optional: [firejail](https://firejail.wordpress.com/) for build sandboxing (use `--no-sandbox` if not installed)

Python deps: `packaging`, `PyYAML`, `GitPython`, `requests` ([requirements.txt](requirements.txt)).

### Config and data locations

- **Root:** `~/.local/share/pygr` (override with `PYGR_ROOT` or `-c DIR`)
- **Declarative config:** `config/packages.conf` — one line per package:
  - `distro:pm:name` — installed via system PM (apt, dnf, pacman, zypper, apk)
  - `github:owner/repo@ref` — built from GitHub
  - `recipe:name@version` — from an added recipe repo
- **Backups:** `backups/`
- **Profile bin (for PATH):** `profiles/default/bin` — run `eval $(pygr path)` to use installed tools

### Build systems (auto-detected from GitHub repos)

Rust (Cargo), Go, Node.js (package.json bin), Python (setup.py/pyproject.toml), CMake, Meson, Makefile, Ruby (Gemfile), Gradle, Maven, Just (justfile).

### Recipe format (for repo-add)

YAML in a Git repo. Minimal:

```yaml
name: myapp
version: "1.0"
source:
  type: github
  repo: owner/repo
  ref: main
```

With build/install and deps:

```yaml
name: myapp
version: "1.0"
source: { type: github, repo: owner/repo, ref: main }
build:
  commands: ["make PREFIX={{prefix}}"]
install:
  commands: ["make install PREFIX={{prefix}}"]
dependencies: ["mylib>=1.0"]
```

`{{prefix}}` is replaced by the install root. Deps use version specs: `>=1.0`, `==2.0`, etc.

### Other installation methods

- **System packages:** Install Python, Git, and deps (python3-yaml, python3-git, python3-requests, python3-packaging or equivalents), then copy `pygr.py` to a dir in `PATH` and `chmod +x`.
- **Manual venv:** `python3 -m venv ~/.local/share/pygr-venv`, `pip install -r requirements.txt`, copy `pygr.py` into the venv, create a wrapper in `~/.local/bin` that runs the venv Python with `pygr.py`.
- **PyInstaller:** `pip install pyinstaller`, `pyinstaller --onefile pygr.py`, copy `dist/pygr` to `PATH`.

### Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest tests/ -v
.venv/bin/ruff check pygr.py tests/
.venv/bin/pre-commit install   # optional
```

Config: [pyproject.toml](pyproject.toml), [.pre-commit-config.yaml](.pre-commit-config.yaml).

### License

See the repository license file.
