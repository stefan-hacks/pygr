<p align="center">
  <img src="icon_pygr.png" width="192" alt="pygr" />
</p>

# pygr — Python GitHub Repository package manager

**pygr** is a [pdrx](https://github.com/stefan-hacks/pdrx)-style package manager: use it **imperatively** (search GitHub, install/remove packages), and it **automatically updates a declarative config** so you can restore your setup with `pygr apply`. Everything is installed **from GitHub** (recipes or direct `owner/repo`).

## Features

- **Imperative + declarative** — Install/remove as usual; `config/packages.conf` is updated automatically. Restore with `pygr apply`.
- **Search GitHub** — `pygr search ripgrep` finds any repository on GitHub (API).
- **Install from GitHub** — By recipe name (from repos you add) or by `owner/repo` (ad-hoc: clone + detect Cargo/Makefile/setup.py/go.mod and build).
- **Reproducible** — Declarative file records `github:owner/repo@ref` or `recipe:name@version` for exact replay.
- **Sync / Apply** — `pygr sync` writes current profile to config; `pygr apply` installs everything in config.
- **Backup / Rollback** — Timestamped backups, profile generations, `pygr rollback`, `pygr export` / `pygr import`.
- **Content-addressed store**, optional **sandbox** (firejail), **binary cache**, **dependency resolution** (recipes).
- **Commands:** `search`, `install`, `remove` (as `uninstall`), `list`, `sync`, `apply`, `status`, `backup`, `generations`, `export`, `import`, `repo-add`, `repo-list`, `upgrade`, `rollback`

## Requirements

- **Python 3.8+**
- **Git**
- **Optional:** [firejail](https://firejail.wordpress.com/) for build sandboxing (use `--no-sandbox` if not installed)

Python dependencies: `packaging`, `PyYAML`, `GitPython`, `requests` (see [requirements.txt](requirements.txt)).

---

## Installation

### Option 1: Bootstrap script (recommended)

From a directory that contains `pygr.py` (e.g. a clone of this repo), or from anywhere to install from GitHub:

```bash
# From repo root (uses local pygr.py)
./install-pygr.sh

# From elsewhere (downloads pygr.py from GitHub)
curl -sL https://raw.githubusercontent.com/stefan-hacks/pygr/main/install-pygr.sh | bash
```

This creates a virtual environment (default: `~/.local/share/pygr-venv`), installs dependencies, and places the `pygr` launcher at `~/.local/bin/pygr`. Ensure `~/.local/bin` is in your `PATH`.

Override locations:

```bash
PYGR_VENV=/opt/pygr-venv ./install-pygr.sh   # custom venv path
PYGR_REPO=https://raw.githubusercontent.com/you/fork/main ./install-pygr.sh  # custom repo URL
```

---

### Option 2: System packages (major Linux distributions)

Install Python, Git, optional firejail, and Python dependencies with your package manager, then copy or symlink `pygr.py` to a directory in your `PATH` (e.g. `/usr/local/bin/pygr`).

#### Debian / Ubuntu (and derivatives)

```bash
sudo apt update
sudo apt install -y python3 python3-pip git firejail
sudo apt install -y python3-yaml python3-git python3-requests python3-packaging
# Copy pygr into PATH
sudo cp pygr.py /usr/local/bin/pygr
sudo chmod +x /usr/local/bin/pygr
```

#### Fedora / RHEL / CentOS

```bash
sudo dnf install -y python3 python3-pip git firejail
sudo dnf install -y python3-pyyaml python3-GitPython python3-requests python3-packaging
sudo cp pygr.py /usr/local/bin/pygr
sudo chmod +x /usr/local/bin/pygr
```

#### Arch Linux

```bash
sudo pacman -S --needed python python-pip git firejail
sudo pacman -S --needed python-yaml python-gitpython python-requests python-packaging
sudo cp pygr.py /usr/local/bin/pygr
sudo chmod +x /usr/local/bin/pygr
```

#### openSUSE (Tumbleweed / Leap)

```bash
sudo zypper install -y python3 python3-pip git firejail
sudo zypper install -y python3-PyYAML python3-GitPython python3-requests python3-packaging
sudo cp pygr.py /usr/local/bin/pygr
sudo chmod +x /usr/local/bin/pygr
```

#### Alpine Linux

```bash
sudo apk add python3 py3-pip git firejail
sudo apk add py3-yaml py3-git py3-requests py3-packaging
sudo cp pygr.py /usr/local/bin/pygr
sudo chmod +x /usr/local/bin/pygr
```

If a distribution does not package GitPython or others, use `pip` in a virtual environment (Option 1 or 3).

---

### Option 3: Virtual environment (manual)

```bash
python3 -m venv ~/.local/share/pygr-venv
~/.local/share/pygr-venv/bin/pip install -r requirements.txt
cp pygr.py ~/.local/share/pygr-venv/bin/
chmod +x ~/.local/share/pygr-venv/bin/pygr.py
# Create a wrapper so you can run "pygr" from anywhere:
echo '#!/bin/sh' > ~/.local/bin/pygr
echo 'exec ~/.local/share/pygr-venv/bin/python ~/.local/share/pygr-venv/bin/pygr.py "$@"' >> ~/.local/bin/pygr
chmod +x ~/.local/bin/pygr
```

---

### Option 4: PyInstaller (standalone binary)

```bash
pip install pyinstaller
pyinstaller --onefile pygr.py
sudo cp dist/pygr /usr/local/bin/
```

---

## Usage

### Search GitHub

Search for any tool on GitHub (uses GitHub API; set `GITHUB_TOKEN` for higher rate limits):

```bash
pygr search ripgrep
pygr search cowsay -n 5
```

### Install packages

Install by **recipe name** (from repos you added) or by **owner/repo** (direct from GitHub; build is auto-detected):

```bash
# From a recipe (add recipe repos first with repo-add)
pygr repo-add myrecipes https://github.com/me/my-pygr-recipes
pygr install cowsay
pygr install "mytool>=1.2"

# Direct from GitHub (clone + build; Cargo.toml, Makefile, setup.py, go.mod supported)
pygr install BurntSushi/ripgrep
pygr install owner/repo@v1.0
```

Every install updates the declarative config (`config/packages.conf`). After installing, add the profile bin to your PATH (see [Data locations](#data-locations)) so you can run the tools — e.g. `eval $(pygr path)` then `ripgrep` or `cowsay`.

### List / Remove

```bash
pygr list
pygr uninstall cowsay    # uninstalls and removes from config
pygr uninstall ripgrep
```

### Sync and Apply (declarative)

- **sync** — Write current profile state to `config/packages.conf`.
- **apply** — Install every package in the declarative config (restore setup).

```bash
pygr sync              # capture current installs into config
pygr apply             # install all from config (e.g. on a new machine)
```

### Status, Backup, Generations, Export/Import

```bash
pygr status            # config path, package count, backups
pygr backup            # timestamped backup of config
pygr backup my-label   # backup with label
pygr generations       # list profile generations and backups
pygr rollback          # switch to previous generation
pygr export            # tarball of config
pygr export my.tgz
pygr import my.tgz     # extract config; then pygr apply
```

### Upgrade

```bash
pygr upgrade cowsay
pygr upgrade           # upgrade all installed
```

### Config directory and sandbox

- Use another config root: `pygr -c /path/to/pygr-root install cowsay`
- **Sandbox** (firejail): `pygr --no-sandbox install ...` to disable
- **Binary cache**: `export PYGR_CACHE_URL=https://...` or `pygr --cache https://... install ...`

---

## Recipe format

Recipes are YAML files (e.g. `cowsay.yaml`) in a repository you add with `repo-add`. Minimal example:

```yaml
name: cowsay
version: "1.0"
source:
  type: github
  repo: owner/cowsay-repo
  ref: main   # or a tag like v1.0, or a full commit hash
```

With build/install and dependencies:

```yaml
name: myapp
version: "2.1.0"
source:
  type: github
  repo: myorg/myapp
  ref: v2.1.0
build:
  commands:
    - "make PREFIX={{prefix}}"
install:
  commands:
    - "make install PREFIX={{prefix}}"
dependencies:
  - "mylib>=1.0"
```

- `{{prefix}}` in commands is replaced by the install root for the package.
- Dependencies are package names with optional version specs: `>=1.0`, `==2.0`, `<3.0`, etc.

---

## Data locations

- **Root:** `~/.local/share/pygr` (override with `PYGR_ROOT` or `-c DIR`)
- **Config:** `$PYGR_ROOT/config/packages.conf` — declarative list (updated on install/remove/sync)
- **Backups:** `$PYGR_ROOT/backups/` — timestamped backup dirs
- **Store:** `$PYGR_ROOT/store`
- **Profiles:** `$PYGR_ROOT/profiles`
- **Repo cache:** `$PYGR_ROOT/repos`
- **Database:** `$PYGR_ROOT/pygr.db`

**Using installed tools:** Executables are in the profile’s `bin` directory. Add it to your `PATH`:

```bash
# One-time (current shell)
eval $(pygr path)

# Or manually
export PATH="$HOME/.local/share/pygr/profiles/default/bin:$PATH"
```

To make it permanent, add one of the above to your `~/.bashrc` or `~/.profile`. Then run `ripgrep`, `cowsay`, etc. as usual. You can also run `pygr path` to see the exact export line.

### Declarative config format

`config/packages.conf` has one line per package:

- `github:owner/repo@ref` — installed from GitHub (ref = branch, tag, or commit)
- `recipe:name@version` — installed from a recipe in an added repo

**Add:** `pygr install owner/repo` or `pygr install recipe_name`  
**Remove:** `pygr uninstall name`  
**Restore:** `pygr apply`

---

## Development and code quality

From the project root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest tests/ -v
.venv/bin/ruff check pygr.py tests/
.venv/bin/ruff format pygr.py tests/
.venv/bin/mypy pygr.py
.venv/bin/bandit -c pyproject.toml -r pygr.py
```

To use [pre-commit](https://pre-commit.com/) (Ruff, mypy, Bandit, and hooks):

```bash
.venv/bin/pre-commit install
```

Configuration: [pyproject.toml](pyproject.toml), [.pre-commit-config.yaml](.pre-commit-config.yaml).

---

## License

See the repository license file.
