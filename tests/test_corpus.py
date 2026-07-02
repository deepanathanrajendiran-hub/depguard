"""D3 — the frozen npm+PyPI micro-corpus (DECISIONS.md §1.2/§1.4/§1.7, editorial note 3).

Reads ONLY the committed `corpus/` (no network) and asserts every curation,
diversity, determinism, and provenance invariant the freeze must uphold. The freeze
script (`scripts/freeze_micro.py`) produces what this test validates; if a
hand-edit ever desyncs a corpus file from `SNAPSHOT.lock`, the snapshot-id
recomputation test goes red.

Provenance rule (implementation note, resolves a §1.7 underdetermination — pinned
here, amendable only with a failing test): §1.7 tags CC-BY-4.0 by GHSA alias OR a
`github.com/advisories` reference, written for the all.zip CVE-primary layout. In
v0.1 we fetch advisories DIRECTLY by GHSA id, so a record whose OWN id is `GHSA-*`
is a GitHub advisory (CC-BY) even with only a CVE alias. The rule is therefore
extended to: CC-BY iff `id` OR any alias starts with `GHSA-`, OR a reference url
contains `github.com/advisories`; else CC0-1.0.
"""

import json
from pathlib import Path

import pytest

from depguard.comparators import VersionParseError, get_comparator
from depguard.corpus_snapshot import compute_snapshot_id, load_snapshot_lock

REPO = Path(__file__).parent.parent
CORPUS = REPO / "corpus"
OSV_DIR = CORPUS / "osv"
EXTRACT_DIR = CORPUS / "depsdev_extract"
ATTRIBUTION = REPO / "NOTICE" / "ATTRIBUTION.md"

CORPUS_ECOSYSTEMS = {"npm", "PyPI"}  # v0.1 micro-corpus (editorial note 3)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _osv_files():
    return sorted(OSV_DIR.rglob("*.json")) if OSV_DIR.is_dir() else []


def _load_records():
    out = []
    for path in _osv_files():
        rec = json.loads(path.read_text())
        out.append((path, rec))
    return out


def _surviving_entries(rec, ecosystem):
    """The §1.2-surviving affected entries for `ecosystem` (comparator-checked)."""
    cmp = get_comparator(ecosystem)
    kept = []
    for e in rec.get("affected", []):
        pkg = e.get("package") or {}
        if pkg.get("ecosystem") != ecosystem:
            continue
        versions = e.get("versions") or []
        semver_ranges = [r for r in e.get("ranges") or [] if r.get("type") == "SEMVER"]
        if not semver_ranges and not versions:
            return None  # would be excluded — must not appear post-curation
        for v in versions:
            cmp.key(v)  # raises VersionParseError if curation was violated
        for r in semver_ranges:
            for ev in r.get("events", []):
                for k, val in ev.items():
                    if k in ("introduced", "fixed", "last_affected") and val != "0":
                        cmp.key(val)
        kept.append(e)
    return kept


def _is_ccby(rec):
    if rec["id"].startswith("GHSA-"):
        return True
    if any(a.startswith("GHSA-") for a in rec.get("aliases", [])):
        return True
    for r in rec.get("references", []):
        if "github.com/advisories" in (r.get("url") or ""):
            return True
    return False


def _semver_ranges(entry):
    return [r for r in entry.get("ranges") or [] if r.get("type") == "SEMVER"]


def _range_event_keys(entry):
    keys = set()
    for r in _semver_ranges(entry):
        for ev in r.get("events", []):
            keys |= set(ev)
    return keys


# --------------------------------------------------------------------------- #
# existence
# --------------------------------------------------------------------------- #

def test_corpus_tree_exists():
    assert CORPUS.is_dir(), "corpus/ not frozen — run scripts/freeze_micro.py"
    assert (CORPUS / "SNAPSHOT.lock").is_file()
    assert (CORPUS / "README.md").is_file()
    assert EXTRACT_DIR.is_dir()
    assert ATTRIBUTION.is_file()


# --------------------------------------------------------------------------- #
# curation (§1.2)
# --------------------------------------------------------------------------- #

def test_every_record_parses_and_passes_curation():
    records = _load_records()
    assert records, "no OSV records in corpus/osv"
    for path, rec in records:
        # ecosystem is encoded in the directory: corpus/osv/<ECO>/<ID>.json
        dir_eco = path.parent.name
        assert dir_eco in CORPUS_ECOSYSTEMS, f"{path} in unexpected ecosystem dir"
        kept = _surviving_entries(rec, dir_eco)
        assert kept, f"{rec['id']} has no surviving {dir_eco} affected entry"
        # every surviving entry must be SEMVER-ranged OR have non-empty versions[]
        for e in kept:
            assert _semver_ranges(e) or (e.get("versions")), (
                f"{rec['id']} entry neither SEMVER nor enumerated"
            )


def test_every_record_ecosystem_is_npm_or_pypi():
    for path, rec in _load_records():
        ecos = {
            (e.get("package") or {}).get("ecosystem")
            for e in rec.get("affected", [])
        }
        assert ecos, f"{rec['id']} has no affected entries"
        assert ecos <= CORPUS_ECOSYSTEMS, f"{rec['id']} carries non-corpus ecosystem {ecos}"


def test_surviving_entries_are_scoring_tier_annotated():
    """Curation annotates each surviving entry with §1.2 scoring_tier."""
    minfix = {"npm", "crates.io", "Go"}
    for path, rec in _load_records():
        dir_eco = path.parent.name
        expected = "membership_and_minfix" if dir_eco in minfix else "membership_only"
        for e in _surviving_entries(rec, dir_eco):
            assert e.get("scoring_tier") == expected, (
                f"{rec['id']} entry scoring_tier {e.get('scoring_tier')} != {expected}"
            )


# --------------------------------------------------------------------------- #
# size + diversity seeds (§4.2 categories)
# --------------------------------------------------------------------------- #

def test_record_count_in_range():
    n = len(_osv_files())
    assert 30 <= n <= 60, f"corpus has {n} records, want 30–60"


def test_at_least_two_withdrawn_records():
    withdrawn = [r for _, r in _load_records() if r.get("withdrawn")]
    assert len(withdrawn) >= 2, f"only {len(withdrawn)} withdrawn records"


def test_at_least_three_false_positive_records():
    """FP material: a bounded SEMVER range (a `fixed`/`last_affected` event) means a
    plausible pinned version at/after the bound is NOT contained."""
    fp = []
    for path, rec in _load_records():
        for e in _surviving_entries(rec, path.parent.name):
            if {"fixed", "last_affected"} & _range_event_keys(e):
                fp.append(rec["id"])
                break
    assert len(fp) >= 3, f"only {len(fp)} false-positive-material records"


def test_at_least_one_no_fix_record():
    """No-fix material: a surviving SEMVER range with `introduced` but no `fixed`
    (open-ended or last_affected) → no published version necessarily clears it."""
    nofix = []
    for path, rec in _load_records():
        for e in _surviving_entries(rec, path.parent.name):
            for r in _semver_ranges(e):
                keys = {k for ev in r.get("events", []) for k in ev}
                if "introduced" in keys and "fixed" not in keys:
                    nofix.append(rec["id"])
                    break
    assert len(nofix) >= 1, "no no-fix (open-ended / last_affected) record"


def test_at_least_one_multi_affected_record():
    multi = [r["id"] for _, r in _load_records() if len(r.get("affected", [])) >= 2]
    assert len(multi) >= 1, "no multi-affected[] record"


# --------------------------------------------------------------------------- #
# determinism (§0.5)
# --------------------------------------------------------------------------- #

def test_snapshot_id_recomputes_from_on_disk_bytes():
    lock = load_snapshot_lock(CORPUS)
    recomputed = compute_snapshot_id(
        CORPUS, lock["capture_date"], lock["curation_ruleset_version"]
    )
    assert recomputed == lock["corpus_snapshot_id"], (
        "corpus_snapshot_id in SNAPSHOT.lock does not match the frozen bytes "
        "(a corpus file was hand-edited without re-freezing)"
    )


def test_snapshot_id_matches_trajectory_schema_form():
    import re
    lock = load_snapshot_lock(CORPUS)
    assert re.fullmatch(
        r"depguard-corpus-\d{4}-\d{2}-\d{2}-[0-9a-f]{12}", lock["corpus_snapshot_id"]
    )


# --------------------------------------------------------------------------- #
# provenance & attribution (§1.7)
# --------------------------------------------------------------------------- #

def test_every_record_carries_provenance_matching_the_rule():
    for path, rec in _load_records():
        prov = rec.get("_provenance")
        assert prov, f"{rec['id']} missing _provenance"
        expected = "CC-BY-4.0" if _is_ccby(rec) else "CC0-1.0"
        assert prov["license"] == expected, (
            f"{rec['id']} tagged {prov['license']} but rule says {expected}"
        )
        assert prov["source"] == "osv"


def test_ccby_records_are_all_listed_in_attribution():
    text = ATTRIBUTION.read_text()
    for path, rec in _load_records():
        if _is_ccby(rec):
            assert rec["id"] in text, f"CC-BY {rec['id']} missing from ATTRIBUTION.md"
            prov = rec["_provenance"]
            assert prov.get("source_url"), f"{rec['id']} CC-BY without source_url"
            assert prov["source_url"] in text, (
                f"{rec['id']} source_url not attributed"
            )


def test_cc0_records_have_no_ghsa_reference():
    """The §1.7 CI assertion — no CC0-tagged record carries a GHSA linkage."""
    cc0 = [r for _, r in _load_records() if r["_provenance"]["license"] == "CC0-1.0"]
    for rec in cc0:
        assert not _is_ccby(rec), f"{rec['id']} tagged CC0 but has a GHSA reference"


def test_at_least_one_cc0_and_one_ccby_record_exercise_both_branches():
    licenses = {r["_provenance"]["license"] for _, r in _load_records()}
    assert "CC0-1.0" in licenses, "no genuine CC0 record — CC0 branch untested"
    assert "CC-BY-4.0" in licenses, "no CC-BY record — attribution branch untested"


# --------------------------------------------------------------------------- #
# deps.dev derived extract (§1.7b — ToS: extract only, never raw responses)
# --------------------------------------------------------------------------- #

def test_extract_exists_for_every_corpus_package():
    system = {"npm": "npm", "PyPI": "pypi"}
    for path, rec in _load_records():
        dir_eco = path.parent.name
        sysname = system[dir_eco]
        for e in _surviving_entries(rec, dir_eco):
            name = (e["package"]["name"])
            f = EXTRACT_DIR / sysname / f"{name}.json"
            assert f.is_file(), f"missing deps.dev extract for {sysname}/{name}"


def test_extract_shape_is_derived_not_raw():
    """Extract carries only the derived fields (§1.7b) — never raw response bodies."""
    required = {"system", "name", "versions", "default_version",
                "advisory_keys_by_version", "captured_at"}
    for f in EXTRACT_DIR.rglob("*.json"):
        ext = json.loads(f.read_text())
        assert required <= set(ext), f"{f} missing derived fields {required - set(ext)}"
        assert isinstance(ext["versions"], list) and ext["versions"]
        assert isinstance(ext["advisory_keys_by_version"], dict)
