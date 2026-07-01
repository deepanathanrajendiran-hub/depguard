"""The §5 verifier: four TOTAL predicates, zero human judgment.

Includes the two regression cases the DECISIONS.md amendments exist to prevent:
- v1.1.0: withdrawn-but-contained ⇒ affected_gold is FALSE (P1 folds the withdrawn
  override), so P1 and P3 can no longer contradict each other.
- v1.2.0: P4 source-agreement compares RAW containment (pre-withdrawn-override), so
  a withdrawn-but-contained alert with a matching deps.dev key scores `agree`,
  never a spurious `disagree`.
"""

import json
from pathlib import Path

import pytest

from depguard.verifier import DepsDevObservation, scoring_tier, verify_verdict

SCHEMAS = Path(__file__).parent.parent / "schemas"


def make_record(**overrides):
    record = {
        "id": "GHSA-35jh-r3h4-6jhm",
        "modified": "2021-03-19T00:00:00Z",
        "withdrawn": None,
        "aliases": ["CVE-2021-23337"],
        "summary": "Command injection in lodash",
        "affected": [
            {
                "package": {"ecosystem": "npm", "name": "lodash", "purl": None},
                "ranges": [
                    {"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "4.17.21"}]}
                ],
                "versions": [],
                "scoring_tier": "membership_and_minfix",
            }
        ],
        "references": [],
        "database_specific": None,
    }
    record.update(overrides)
    return record


def make_verdict(**overrides):
    verdict = {
        "alert_id": "a1",
        "affected": True,
        "minimal_fixed_version": "4.17.21",
        "withdrawn": False,
        "cvss3_score": None,
        "evidence_ids": ["e1"],
        "source_agreement": "agree",
        "reconciliation_note": "",
    }
    verdict.update(overrides)
    return verdict


PUBLISHED = ["4.17.19", "4.17.20", "4.17.21", "4.17.22"]

AGREEING_DEPSDEV = DepsDevObservation(
    package_known=True,
    version_advisory_keys=["GHSA-35jh-r3h4-6jhm"],
    package_advisory_keys=["GHSA-35jh-r3h4-6jhm"],
)


def score(verdict, record=None, depsdev=AGREEING_DEPSDEV, published=PUBLISHED,
          ecosystem="npm", name="lodash", pinned="4.17.20"):
    return verify_verdict(
        verdict,
        ecosystem=ecosystem,
        name=name,
        pinned_version=pinned,
        osv_record=record or make_record(),
        published_versions=published,
        depsdev=depsdev,
    )


# ---------- the happy path ----------

def test_fully_correct_verdict_passes_all_four_predicates():
    result = score(make_verdict())
    assert result.status == "scored"
    assert result.correct is True
    assert all(p.passed in (True, None) for p in result.predicates.values())


# ---------- P1: containment with the withdrawn override folded in ----------

def test_p1_catches_wrong_affected():
    result = score(make_verdict(affected=False))
    assert result.predicates["P1"].passed is False
    assert result.correct is False


def test_p1_withdrawn_but_contained_gold_is_not_affected():
    """v1.1.0 regression: a correct verdict on a withdrawn advisory reports
    affected=False even though the version IS in range — and must PASS."""
    record = make_record(withdrawn="2024-01-01T00:00:00Z")
    correct_verdict = make_verdict(
        affected=False, withdrawn=True, minimal_fixed_version=None
    )
    result = score(correct_verdict, record)
    assert result.predicates["P1"].passed is True
    assert result.predicates["P3"].passed is True
    assert result.correct is True

    # and claiming affected=True on the withdrawn record must FAIL P1
    wrong = make_verdict(affected=True, withdrawn=True, minimal_fixed_version=None)
    assert score(wrong, record).predicates["P1"].passed is False


# ---------- P2: minimal-fix, scored only on the minfix tier ----------

def test_p2_catches_wrong_minimal_fix():
    result = score(make_verdict(minimal_fixed_version="4.17.22"))
    assert result.predicates["P2"].passed is False
    assert result.correct is False


def test_p2_not_scored_on_membership_only_ecosystems():
    record = make_record(
        id="GHSA-pypi-test-0001",
        aliases=[],
        affected=[{
            "package": {"ecosystem": "PyPI", "name": "requests", "purl": None},
            "ranges": [
                {"type": "SEMVER", "events": [{"introduced": "2.0.0"}, {"fixed": "2.31.0"}]}
            ],
            "versions": [],
            "scoring_tier": "membership_only",
        }],
    )
    depsdev = DepsDevObservation(True, ["GHSA-pypi-test-0001"], ["GHSA-pypi-test-0001"])
    # deliberately absurd minimal_fixed_version: P2 must be exempt on PyPI
    verdict = make_verdict(minimal_fixed_version="9.9.9")
    result = score(
        verdict, record, depsdev,
        published=["2.30.0", "2.31.0"],
        ecosystem="PyPI", name="requests", pinned="2.30.0",
    )
    assert result.predicates["P2"].passed is None  # not scored (§5 P2)
    assert result.correct is True


# ---------- P3: withdrawn bool ----------

def test_p3_catches_wrong_withdrawn_flag():
    result = score(make_verdict(withdrawn=True))
    assert result.predicates["P3"].passed is False


# ---------- P4: source agreement on RAW containment ----------

def test_p4_agree_gold_rejects_claimed_disagreement():
    result = score(make_verdict(source_agreement="disagree", reconciliation_note="x"))
    assert result.predicates["P4"].passed is False


def test_p4_disagree_gold_requires_disagree_plus_note():
    # package knows the advisory, but the checked version carries no key while
    # OSV says contained ⇒ genuine per-version contradiction (§1.3)
    depsdev = DepsDevObservation(
        package_known=True,
        version_advisory_keys=[],
        package_advisory_keys=["GHSA-35jh-r3h4-6jhm"],
    )
    good = make_verdict(source_agreement="disagree", reconciliation_note="deps.dev lacks key")
    assert score(good, depsdev=depsdev).predicates["P4"].passed is True

    empty_note = make_verdict(source_agreement="disagree", reconciliation_note="")
    assert score(empty_note, depsdev=depsdev).predicates["P4"].passed is False

    wrong_enum = make_verdict(source_agreement="agree")
    assert score(wrong_enum, depsdev=depsdev).predicates["P4"].passed is False


def test_p4_single_source_when_advisory_unknown_to_depsdev():
    depsdev = DepsDevObservation(
        package_known=True,
        version_advisory_keys=["GHSA-unrelated-0000"],
        package_advisory_keys=["GHSA-unrelated-0000"],
    )
    result = score(make_verdict(source_agreement="single_source"), depsdev=depsdev)
    assert result.predicates["P4"].passed is True
    assert result.agreement_metric_eligible is False  # excluded from agreement rate


def test_p4_single_source_when_package_absent_entirely():
    result = score(make_verdict(source_agreement="single_source"), depsdev=None)
    assert result.predicates["P4"].passed is True
    assert result.agreement_metric_eligible is False


def test_p4_uses_raw_containment_not_withdrawn_adjusted():
    """v1.2.0 regression: withdrawn-but-contained + matching key = agree."""
    record = make_record(withdrawn="2024-01-01T00:00:00Z")
    verdict = make_verdict(
        affected=False, withdrawn=True, minimal_fixed_version=None,
        source_agreement="agree",
    )
    result = score(verdict, record)
    assert result.predicates["P4"].passed is True
    assert result.correct is True


def test_p4_alias_resolution_matches_ghsa_via_cve_record():
    record = make_record(id="CVE-2021-23337", aliases=["GHSA-35jh-r3h4-6jhm"])
    result = score(make_verdict(), record)  # deps.dev key is the GHSA alias
    assert result.predicates["P4"].passed is True


# ---------- exclusion & totality ----------

def test_empty_e_a_is_excluded_not_scored_false():
    record = make_record(affected=[])
    result = score(make_verdict(), record)
    assert result.status == "excluded"
    assert result.correct is None


def test_correct_is_the_conjunction_of_all_four():
    result = score(make_verdict(withdrawn=True))  # only P3 wrong
    assert result.predicates["P1"].passed is True
    assert result.correct is False


# ---------- registry consistency ----------

def test_scoring_tier_matches_the_normative_registry():
    with open(SCHEMAS / "ecosystem_system_map.json") as f:
        registry = json.load(f)
    for eco in registry["corpus_ecosystems"]:
        assert scoring_tier(eco) == registry["ecosystems"][eco]["scoring_tier"]
    with pytest.raises(LookupError):
        scoring_tier("Maven")
