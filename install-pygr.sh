#!/bin/bash
set -e
echo "Installing pygr in a virtual environment..."

# Create virtual environment
VENV_DIR="${PYGR_VENV:-$HOME/.local/share/pygr-venv}"
python3 -m venv "$VENV_DIR"

# Install dependencies (pygr uses argparse, not click)
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install pyyaml GitPython requests packaging

# Use local pygr.py if present, otherwise download
if [ -f "pygr.py" ]; then
    cp pygr.py "$VENV_DIR/bin/pygr.py"
    chmod +x "$VENV_DIR/bin/pygr.py"
else
    PYGR_REPO="${PYGR_REPO:-https://raw.githubusercontent.com/stefan-hacks/pygr/main}"
    curl -sL "$PYGR_REPO/pygr.py" -o "$VENV_DIR/bin/pygr.py"
    chmod +x "$VENV_DIR/bin/pygr.py"
fi

# Create wrapper script
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/pygr" << EOF
#!/bin/bash
exec "$VENV_DIR/bin/python" "$VENV_DIR/bin/pygr.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/pygr"

echo "pygr installed at $HOME/.local/bin/pygr (venv: $VENV_DIR)."
echo "Ensure ~/.local/bin is in your PATH."
