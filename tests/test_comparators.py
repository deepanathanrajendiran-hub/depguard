"""Ecosystem-vetted comparators (DECISIONS.md §1.2 comparator policy).

Only four ecosystems ship a comparator: npm/crates.io (semver), Go (module semver,
optional leading 'v'), PyPI (PEP440 via packaging). Everything else must raise —
no vetted comparator means containment is not mechanically decidable.
"""

import pytest

from depguard.comparators import VersionParseError, get_comparator


# ---------- npm (strict semver) ----------

def test_npm_orders_numerically_not_lexicographically():
    c = get_comparator("npm")
    assert c.lt("1.9.0", "1.10.0")


def test_npm_prerelease_sorts_before_release():
    c = get_comparator("npm")
    assert c.lt("1.0.0-alpha.1", "1.0.0")


def test_npm_equality_ignores_build_metadata():
    c = get_comparator("npm")
    assert c.eq("1.2.3+build.5", "1.2.3")


def test_npm_rejects_v_prefix():
    c = get_comparator("npm")
    with pytest.raises(VersionParseError):
        c.key("v1.2.3")


def test_npm_rejects_partial_and_tag_versions():
    c = get_comparator("npm")
    for bad in ("1.2", "latest", "", "^1.2.3"):
        with pytest.raises(VersionParseError):
            c.key(bad)


# ---------- crates.io (strict semver) ----------

def test_crates_strict_semver():
    c = get_comparator("crates.io")
    assert c.lt("0.9.9", "0.10.0")
    with pytest.raises(VersionParseError):
        c.key("1.2")


# ---------- Go (module semver, optional leading v) ----------

def test_go_accepts_v_prefix_and_bare_equally():
    c = get_comparator("Go")
    assert c.eq("v1.2.3", "1.2.3")


def test_go_pseudo_version_sorts_before_next_release():
    c = get_comparator("Go")
    # v0.0.0-20200902074654-038fdea0a05b is a prerelease of 0.0.0
    assert c.lt("v0.0.0-20200902074654-038fdea0a05b", "v0.1.0")


def test_go_incompatible_suffix_is_build_metadata():
    c = get_comparator("Go")
    assert c.eq("v2.0.0+incompatible", "2.0.0")


# ---------- PyPI (PEP440) ----------

def test_pypi_equality_across_zero_padding():
    c = get_comparator("PyPI")
    assert c.eq("1.0", "1.0.0")


def test_pypi_rc_before_final_and_post_after():
    c = get_comparator("PyPI")
    assert c.lt("2.0.0rc1", "2.0.0")
    assert c.lt("1.0", "1.0.post1")


def test_pypi_rejects_garbage():
    c = get_comparator("PyPI")
    with pytest.raises(VersionParseError):
        c.key("not-a-version")


# ---------- shared behavior ----------

def test_sort_orders_ascending():
    c = get_comparator("npm")
    assert c.sort(["1.10.0", "1.2.0", "1.9.0"]) == ["1.2.0", "1.9.0", "1.10.0"]


def test_unvetted_ecosystems_have_no_comparator():
    for eco in ("Maven", "RubyGems", "NuGet", "Packagist"):
        with pytest.raises(LookupError):
            get_comparator(eco)
