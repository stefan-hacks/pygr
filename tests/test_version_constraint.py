"""Tests for VersionConstraint."""

import pytest

# Import after conftest sets PYGR_ROOT
import pygr  # noqa: E402


class TestVersionConstraint:
    """VersionConstraint parsing and matching."""

    def test_any_empty_spec(self):
        c = pygr.VersionConstraint("")
        assert c.op == "any"
        assert c.matches("1.0.0")
        assert c.matches("0.0.1")

    def test_equals_implicit(self):
        c = pygr.VersionConstraint("1.2.3")
        assert c.op == "=="
        assert c.version == "1.2.3"
        assert c.matches("1.2.3")
        assert not c.matches("1.2.4")

    def test_equals_explicit(self):
        c = pygr.VersionConstraint("== 2.0")
        assert c.matches("2.0")
        assert not c.matches("2.1")

    def test_gte(self):
        c = pygr.VersionConstraint(">= 1.0")
        assert c.matches("1.0")
        assert c.matches("2.0")
        assert not c.matches("0.9")

    def test_gt(self):
        c = pygr.VersionConstraint("> 1.0")
        assert not c.matches("1.0")
        assert c.matches("1.1")

    def test_lte(self):
        c = pygr.VersionConstraint("<= 2.0")
        assert c.matches("2.0")
        assert c.matches("1.0")
        assert not c.matches("2.1")

    def test_lt(self):
        c = pygr.VersionConstraint("< 2.0")
        assert c.matches("1.9")
        assert not c.matches("2.0")

    def test_invalid_version_on_match_raises(self):
        # Invalid version string in spec causes error when matching (parse in matches())
        try:
            from packaging.version import InvalidVersion

            c = pygr.VersionConstraint("== not-a-version")
            with pytest.raises(InvalidVersion):
                c.matches("1.0")
        except ImportError:
            pytest.skip("packaging.InvalidVersion not available")
