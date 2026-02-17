## Installation Instructions

### Option 1: Install Dependencies via System Package Manager (Recommended)

#### **Debian/Ubuntu** (and derivatives)
```bash
sudo apt update
sudo apt install python3 python3-pip git firejail
sudo apt install python3-click python3-yaml python3-git python3-requests python3-packaging
# Download pygr.py
wget https://github.com/stefan-hacks/pygr.py -O /usr/local/bin/pygr
chmod +x /usr/local/bin/pygr
```

#### **Fedora**
```bash
sudo dnf install python3 python3-pip git firejail
sudo dnf install python3-click python3-pyyaml python3-GitPython python3-requests python3-packaging
# Download pygr.py and place in /usr/local/bin
```

#### **Arch Linux**
```bash
sudo pacman -S python python-pip git firejail
sudo pacman -S python-click python-yaml python-gitpython python-requests python-packaging
# Download pygr.py
```

#### **openSUSE**
```bash
sudo zypper install python3 python3-pip git firejail
sudo zypper install python3-click python3-PyYAML python3-GitPython python3-requests python3-packaging
```

### Option 2: Bootstrap Installer (Automatic Virtual Environment)

Create a small installer script `install-pygr.sh`:

```bash
#!/bin/bash
set -e
echo "Installing pygr in a virtual environment..."

# Create virtual environment
VENV_DIR="$HOME/.local/share/pygr-venv"
python3 -m venv "$VENV_DIR"

# Install dependencies
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install click pyyaml GitPython requests packaging

# Download pygr.py
curl -L https://raw.githubusercontent.com/your-repo/pygr/main/pygr.py -o "$VENV_DIR/bin/pygr"
chmod +x "$VENV_DIR/bin/pygr"

# Create wrapper script
cat > "$HOME/.local/bin/pygr" << EOF
#!/bin/bash
exec "$VENV_DIR/bin/python" "$VENV_DIR/bin/pygr" "\$@"
EOF
chmod +x "$HOME/.local/bin/pygr"

echo "pygr installed. Make sure ~/.local/bin is in your PATH."
```

Run: `bash install-pygr.sh`

### Option 3: Standalone Binary with PyInstaller

```bash
# Install PyInstaller
pip install pyinstaller

# Create single executable
pyinstaller --onefile pygr.py

# The binary is in dist/pygr; copy to /usr/local/bin
sudo cp dist/pygr /usr/local/bin/
```

### Option 4: Direct pip Installation (if allowed)

```bash
pip install click pyyaml GitPython requests packaging
# Then run pygr.py directly
```

---

## Usage Examples

```bash
# Add a recipe repository
pygr repo-add myrecipes https://github.com/me/my-pygr-recipes

# Install a package
pygr install cowsay
pygr install "python>=3.8"

# List installed
pygr list

# Uninstall
pygr uninstall cowsay

# Upgrade
pygr upgrade cowsay
pygr upgrade  # upgrade all

# Rollback
pygr rollback
```

---

## Notes

- **Sandboxing**: Requires `firejail` installed. Disable with `--no-sandbox`.
- **Binary Cache**: Set `PYGR_CACHE_URL` environment variable or use `--cache`.
- **Recipes**: Place YAML files in a Git repository; each file defines one package.

This single-file implementation includes all advanced features while remaining manageable. The installation methods ensure users can get pygr running without manual dependency headaches.
