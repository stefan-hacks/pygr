<p align="center">
  <img src="icon_pygr.png" width="192" alt="pygr" />
</p>

# pygr — Python GitHub Repository package manager

**pygr** is a single-file package manager that builds and installs software from GitHub repositories using declarative YAML recipes. It provides content-addressed builds, SAT-like dependency resolution with version constraints, optional sandboxed builds (firejail), binary cache support, and transactional profile generations (rollback).

## Features

- **GitHub source fetching** with tree hashing for reproducible builds
- **Dependency resolution** with version constraints (`>=`, `==`, `<`, etc.)
- **Sandboxed builds** via [firejail](https://firejail.wordpress.com/) (optional)
- **Content-addressed store** so identical builds are deduplicated
- **Binary cache** support to download pre-built artifacts
- **Transactional profiles** — install/upgrade creates a new generation; `pygr rollback` reverts to the previous one
- **Commands:** `repo-add`, `repo-list`, `install`, `list`, `uninstall`, `upgrade`, `rollback`

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

### Add a recipe repository

Recipes are YAML files in a Git repository. Add a repo that contains them:

```bash
pygr repo-add myrecipes https://github.com/me/my-pygr-recipes
pygr repo-list
```

### Install packages

```bash
# Install one or more packages (by name from your added repos)
pygr install cowsay
pygr install cowsay hello

# Version constraints (optional)
pygr install "mytool>=1.2"
pygr install "mytool==2.0"
```

### List installed packages

```bash
pygr list
```

### Uninstall

```bash
pygr uninstall cowsay
pygr uninstall cowsay hello
```

### Upgrade

```bash
pygr upgrade cowsay    # upgrade one package
pygr upgrade           # upgrade all installed packages
```

### Rollback

If an install or upgrade causes issues, switch back to the previous profile generation:

```bash
pygr rollback
```

### Sandbox and binary cache

- **Disable sandbox** (e.g. if firejail is not installed):  
  `pygr --no-sandbox install cowsay`

- **Binary cache** (optional): set a base URL so pygr can download pre-built artifacts instead of building:
  ```bash
  export PYGR_CACHE_URL=https://my-cache.example.com/pygr
  pygr install cowsay
  ```
  Or: `pygr --cache https://my-cache.example.com/pygr install cowsay`

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

- **Root:** `~/.local/share/pygr` (override with environment variable `PYGR_ROOT`)
- **Store:** `$PYGR_ROOT/store`
- **Profiles:** `$PYGR_ROOT/profiles`
- **Repo cache:** `$PYGR_ROOT/repos`
- **Database:** `$PYGR_ROOT/pygr.db`

Installed binaries are symlinked into the active profile’s `bin` directory; add that directory to your `PATH` if you want to run them directly (see your profile path under `$PYGR_ROOT/profiles`).

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
