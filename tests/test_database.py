"""Tests for Database."""

import pygr  # noqa: E402


def test_database_store_package():
    """Add and retrieve store package."""
    db = pygr.Database()
    db.add_store_package("hash123", "pkg", "1.0", "/path/to/store/hash123-pkg-1.0")
    row = db.get_store_package("hash123")
    assert row is not None
    assert row[0] == "hash123"
    assert row[1] == "pkg"
    assert row[2] == "1.0"
    assert row[3] == "/path/to/store/hash123-pkg-1.0"
    db.close()


def test_database_repos():
    """Add and list repos."""
    db = pygr.Database()
    db.add_repo("myrepo", "https://github.com/user/repo")
    repos = db.list_repos()
    assert any(name == "myrepo" and url == "https://github.com/user/repo" for name, url in repos)
    db.close()


def test_database_profile_generations():
    """Add and get profile generations."""
    db = pygr.Database()
    db.add_profile_generation("default", 1, ["hash1", "hash2"])
    gen, pkgs = db.get_latest_profile_generation("default")
    assert gen == 1
    assert pkgs == ["hash1", "hash2"]
    db.add_profile_generation("default", 2, ["hash1", "hash2", "hash3"])
    gen2, pkgs2 = db.get_latest_profile_generation("default")
    assert gen2 == 2
    assert pkgs2 == ["hash1", "hash2", "hash3"]
    pkg_list = db.get_profile_generation("default", 1)
    assert pkg_list == ["hash1", "hash2"]
    db.close()
