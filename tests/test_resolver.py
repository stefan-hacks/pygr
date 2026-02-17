"""Tests for dependency Resolver."""

import pytest

import pygr  # noqa: E402


def _recipe(name: str, version: str, deps=None):
    return pygr.Recipe(
        {
            "name": name,
            "version": version,
            "source": {"type": "github", "repo": f"test/{name}", "ref": "main"},
            "dependencies": deps or [],
        }
    )


def test_resolve_single():
    """Resolve a single package with no deps."""
    recipes = {"foo": [_recipe("foo", "1.0")]}
    r = pygr.Resolver(recipes)
    order = r.resolve("foo")
    assert len(order) == 1
    assert order[0].name == "foo"
    assert order[0].version == "1.0"


def test_resolve_with_deps():
    """Resolve package and its dependency in topological order."""
    recipes = {
        "app": [_recipe("app", "1.0", ["lib>=1.0"])],
        "lib": [_recipe("lib", "1.0")],
    }
    r = pygr.Resolver(recipes)
    order = r.resolve("app")
    names = [x.name for x in order]
    assert "lib" in names
    assert "app" in names
    assert names.index("lib") < names.index("app")


def test_resolve_version_constraint():
    """Resolver picks version satisfying constraint."""
    recipes = {
        "pkg": [
            _recipe("pkg", "1.0"),
            _recipe("pkg", "2.0"),
            _recipe("pkg", "3.0"),
        ],
    }
    r = pygr.Resolver(recipes)
    order = r.resolve("pkg", ">=2.0")
    assert len(order) == 1
    assert order[0].version == "3.0"


def test_resolve_no_recipe_raises():
    """Missing package raises."""
    r = pygr.Resolver({})
    with pytest.raises(Exception, match="No recipe found"):
        r.resolve("nonexistent")


def test_resolve_no_matching_version_raises():
    """Constraint that no version satisfies raises."""
    recipes = {"pkg": [_recipe("pkg", "1.0")]}
    r = pygr.Resolver(recipes)
    with pytest.raises(Exception, match="No version"):
        r.resolve("pkg", ">=2.0")


def test_resolve_circular_raises():
    """Circular dependency raises."""
    recipes = {
        "a": [_recipe("a", "1.0", ["b"])],
        "b": [_recipe("b", "1.0", ["a"])],
    }
    r = pygr.Resolver(recipes)
    with pytest.raises(Exception, match="Circular"):
        r.resolve("a")


def test_resolve_incompatible_dep_version_raises():
    """Two branches requiring different versions of same dep raises Incompatible."""
    recipes = {
        "app": [_recipe("app", "1.0", ["left", "right"])],
        "left": [_recipe("left", "1.0", ["lib==1.0"])],
        "right": [_recipe("right", "1.0", ["lib==2.0"])],
        "lib": [_recipe("lib", "1.0"), _recipe("lib", "2.0")],
    }
    r = pygr.Resolver(recipes)
    with pytest.raises(Exception, match="Incompatible"):
        r.resolve("app")
