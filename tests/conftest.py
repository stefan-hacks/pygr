"""Pytest configuration: use a temporary PYGR_ROOT so tests don't touch real data."""

import os
import shutil
import tempfile

import pytest

# Set PYGR_ROOT before any test module imports pygr (so pygr's module-level constants use it)
_PYGR_TEST_ROOT = tempfile.mkdtemp(prefix="pygr_test_")
os.environ["PYGR_ROOT"] = _PYGR_TEST_ROOT


@pytest.fixture(scope="session", autouse=True)
def _cleanup_pygr_root():
    """Remove test PYGR_ROOT and env var after all tests."""
    yield
    os.environ.pop("PYGR_ROOT", None)
    shutil.rmtree(_PYGR_TEST_ROOT, ignore_errors=True)
