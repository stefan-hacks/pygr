"""Tests for Recipe loading and validation."""

import pytest
import yaml

import pygr  # noqa: E402


def test_load_recipe_minimal(tmp_path):
    """Load a minimal valid recipe from file."""
    recipe_file = tmp_path / "pkg.yaml"
    recipe_file.write_text(
        yaml.dump(
            {
                "name": "foo",
                "version": "1.0",
                "source": {"type": "github", "repo": "user/foo", "ref": "main"},
            }
        )
    )
    r = pygr.load_recipe_file(str(recipe_file))
    assert r.name == "foo"
    assert r.version == "1.0"
    assert r.source["repo"] == "user/foo"
    assert r.dependencies == []


def test_load_recipe_with_deps(tmp_path):
    """Recipe with build, install, dependencies."""
    recipe_file = tmp_path / "pkg.yaml"
    recipe_file.write_text(
        yaml.dump(
            {
                "name": "bar",
                "version": "2.0",
                "source": {"type": "github", "repo": "user/bar", "ref": "v2.0"},
                "build": {"commands": ["echo build"]},
                "install": {"commands": ["echo install"]},
                "dependencies": ["baz>=1.0"],
            }
        )
    )
    r = pygr.load_recipe_file(str(recipe_file))
    assert r.name == "bar"
    assert r.dependencies == ["baz>=1.0"]
    assert r.to_dict()["version"] == "2.0"


def test_recipe_validation_non_github():
    """Only GitHub source type is allowed."""
    with pytest.raises(AssertionError, match="Only GitHub"):
        pygr.Recipe(
            {
                "name": "x",
                "version": "1",
                "source": {"type": "gitlab", "repo": "a/b", "ref": "x"},
            }
        )


def test_recipe_validation_missing_repo():
    """Source must have repo."""
    with pytest.raises(AssertionError):
        pygr.Recipe(
            {
                "name": "x",
                "version": "1",
                "source": {"type": "github", "ref": "main"},
            }
        )


def test_recipe_validation_missing_ref():
    """Source must have ref."""
    with pytest.raises(AssertionError):
        pygr.Recipe(
            {
                "name": "x",
                "version": "1",
                "source": {"type": "github", "repo": "a/b"},
            }
        )


def test_find_recipes_in_dir(tmp_path):
    """find_recipes_in_dir discovers YAML recipes."""
    (tmp_path / "a.yaml").write_text(
        yaml.dump(
            {
                "name": "a",
                "version": "1",
                "source": {"type": "github", "repo": "u/a", "ref": "main"},
            }
        )
    )
    (tmp_path / "b.yml").write_text(
        yaml.dump(
            {
                "name": "b",
                "version": "1",
                "source": {"type": "github", "repo": "u/b", "ref": "main"},
            }
        )
    )
    (tmp_path / "ignore.txt").write_text("not a recipe")
    recipes = pygr.find_recipes_in_dir(str(tmp_path))
    names = {r.name for r in recipes}
    assert names == {"a", "b"}
