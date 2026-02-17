"""Tests for Store and utility functions."""

import pygr  # noqa: E402


def test_compute_hash_deterministic():
    """compute_hash is deterministic."""
    data = {"a": 1, "b": 2}
    h1 = pygr.compute_hash(data)
    h2 = pygr.compute_hash(data)
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex


def test_compute_hash_canonical():
    """Different key order produces same hash (canonical JSON)."""
    assert pygr.compute_hash({"a": 1, "b": 2}) == pygr.compute_hash({"b": 2, "a": 1})


def test_store_derivation_hash():
    """Store.compute_derivation_hash depends on recipe, source_hash, deps."""
    r = pygr.Recipe(
        {
            "name": "pkg",
            "version": "1.0",
            "source": {"type": "github", "repo": "u/p", "ref": "main"},
            "dependencies": [],
        }
    )
    store = pygr.Store()
    h1 = store.compute_derivation_hash(r, "abc", [])
    h2 = store.compute_derivation_hash(r, "abc", [])
    assert h1 == h2
    h3 = store.compute_derivation_hash(r, "abd", [])
    assert h1 != h3
    h4 = store.compute_derivation_hash(r, "abc", ["dep1"])
    assert h1 != h4
