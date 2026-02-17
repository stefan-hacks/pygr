"""Tests for CLI (subcommands and help)."""

import subprocess
import sys
from pathlib import Path

# Run pygr as script (project root has pygr.py). PYGR_ROOT is set by conftest.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYGR_SCRIPT = PROJECT_ROOT / "pygr.py"


def _run_pygr(*args):
    return subprocess.run(
        [sys.executable, str(PYGR_SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


def test_cli_requires_command():
    """CLI requires a subcommand."""
    result = _run_pygr()
    assert result.returncode != 0
    assert "required" in result.stderr.lower() or "subcommand" in result.stderr.lower()


def test_cli_help():
    """pygr --help lists commands."""
    result = _run_pygr("--help")
    assert result.returncode == 0
    assert "pygr" in result.stdout
    assert "install" in result.stdout
    assert "repo-add" in result.stdout


def test_cli_install_help():
    """pygr install --help shows package argument."""
    result = _run_pygr("install", "--help")
    assert result.returncode == 0
    assert "packages" in result.stdout or "package" in result.stdout


def test_cli_list_no_packages():
    """pygr list with no packages prints message."""
    result = _run_pygr("list")
    assert result.returncode == 0
    assert "No packages" in result.stdout or "generation" in result.stdout.lower()


def test_cli_rollback_no_previous():
    """pygr rollback with no previous generation."""
    result = _run_pygr("rollback")
    assert result.returncode == 0
    assert "No previous" in result.stdout or "generation" in result.stdout.lower()
