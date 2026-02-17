"""Tests for DeclarativeConfig and distro/github/recipe spec parsing."""
import tempfile
from pathlib import Path

import pygr  # noqa: E402


def test_distro_spec_parsing():
    """distro:pm:name is parsed and display name is the package name."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
        f.write("distro:apt:ripgrep\n")
        f.write("distro:dnf:bat\n")
        f.flush()
        path = f.name
    try:
        cfg = pygr.DeclarativeConfig(path)
        entries = cfg.read_entries()
        assert len(entries) == 2
        assert entries[0] == ("distro:apt:ripgrep", "ripgrep")
        assert entries[1] == ("distro:dnf:bat", "bat")
    finally:
        Path(path).unlink(missing_ok=True)


def test_add_and_remove_distro():
    """Add distro entry and remove by name."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
        f.write("")
        f.flush()
        path = f.name
    try:
        cfg = pygr.DeclarativeConfig(path)
        cfg.add_entry("distro:apt:htop")
        entries = cfg.read_entries()
        assert len(entries) == 1
        assert entries[0][1] == "htop"
        removed = cfg.remove_by_name("htop")
        assert removed == "distro:apt:htop"
        assert cfg.read_entries() == []
    finally:
        Path(path).unlink(missing_ok=True)
