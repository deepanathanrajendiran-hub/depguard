"""`metrics.py::correctness` MUST be the §5 four-predicate verifier, not a lookalike.

Until v1.1.0 the README, RELEASE_NOTES and DECISIONS all said results were "scored by
the same 4-predicate verifier", but `score_trajectory` called a private field-equality
check in `metrics.py` and never called `depguard/verifier.py::verify_verdict` at all.
Two behaviours documented in verifier.py were therefore never enforced on any published
number:

  * P4's rule that a `disagree` verdict MUST carry a non-empty `reconciliation_note`
    (§3.3) — field equality passes an empty note as long as the state string matches.
  * The exclusion path: an alert whose E_A is empty after the membership filter, or
    whose ranges are unresolvable, is NOT scoreable and must leave the denominator
    rather than be graded on field equality.

The exclusion path is also load-bearing for the prose slice (D15): a redacted record
raises RangeUnresolvableError, and that must read as "not scoreable here", never as
"this arm got it wrong".
"""

import json
from pathlib import Path

import pytest

from depguard.graph import build_gold, run_graph
from depguard.metrics import aggregate, correctness, score_trajectory
from depguard.snapshot import Snapshot
from golden.seeds import SEED_INPUTS

REPO = Path(__file__).resolve().parent.parent
DISAGREE = REPO / "tests" / "fixtures" / "disagree_corpus"
MINI = REPO / "tests" / "fixtures" / "mini_corpus"


def _verdict(**over):
    v = {
        "alert_id": "d1",
        "affected": False,
        "minimal_fixed_version": None,
        "withdrawn": False,
        "cvss3_score": None,
        "evidence_ids": ["ev-osv-d1"],
        "source_agreement": "disagree",
        "reconciliation_note": "OSV and deps.dev disagree on this version",
    }
    v.update(over)
    return v


def _trajectory(verdicts, *, alert):
    return {
        "input": {
            "manifest": [{
                "ecosystem": alert["ecosystem"], "name": alert["name"],
                "pinned_version": alert["pinned_version"],
                "purl": f"pkg:{alert['ecosystem']}/{alert['name']}@{alert['pinned_version']}",
            }],
            "alerts": [alert],
        },
        "verdicts": verdicts,
    }


DISAGREE_ALERT = {
    "alert_id": "d1", "ecosystem": "npm", "name": "gizmo",
    "pinned_version": "2.0.0", "advisory_id": "GHSA-dis-0001", "source": "scanner",
}


def _disagree_gold():
    snap = Snapshot(DISAGREE)
    return build_gold(
        {"manifest": [{"ecosystem": "npm", "name": "gizmo", "pinned_version": "2.0.0",
                       "purl": "pkg:npm/gizmo@2.0.0"}],
         "alerts": [DISAGREE_ALERT]},
        snap,
    ), snap


def test_the_fixture_really_produces_a_disagree_gold():
    """Guards the test itself: if the fixture stops disagreeing, the P4 test below
    would pass vacuously."""
    gold, _ = _disagree_gold()
    assert gold["gold_verdicts"][0]["source_agreement"] == "disagree"


def test_p4_empty_reconciliation_note_fails_correctness():
    """THE delegation test. Field equality passes this verdict (source_agreement
    matches gold exactly); verify_verdict fails it because §3.3 requires a note."""
    gold, snap = _disagree_gold()
    traj = _trajectory([_verdict(reconciliation_note="")], alert=DISAGREE_ALERT)
    result = correctness(traj, gold, snap)
    assert result["score"] == 0.0, (
        "a disagree verdict with an empty reconciliation_note was scored correct — "
        "correctness is not routing through verify_verdict"
    )
    assert result["fails"]


def test_p4_with_a_note_passes():
    gold, snap = _disagree_gold()
    traj = _trajectory([_verdict()], alert=DISAGREE_ALERT)
    assert correctness(traj, gold, snap)["score"] == 1.0


def test_unscoreable_alert_is_excluded_from_the_denominator():
    """An ECOSYSTEM-only record has an empty E_A after the membership filter, so
    verify_verdict returns status='excluded'. It must leave the denominator, not be
    graded — otherwise the prose slice would score redacted records as wrong answers."""
    snap = Snapshot(MINI)
    alert = {"alert_id": "m1", "ecosystem": "npm", "name": "widget",
             "pinned_version": "1.0.0", "advisory_id": "GHSA-mini-eco-0002",
             "source": "scanner"}
    inp = {"manifest": [{"ecosystem": "npm", "name": "widget", "pinned_version": "1.0.0",
                         "purl": "pkg:npm/widget@1.0.0"}], "alerts": [alert]}
    gold = build_gold(inp, snap)
    # a deliberately wrong verdict — it must still not count against the arm
    traj = _trajectory(
        [_verdict(alert_id="m1", affected=True, source_agreement="agree",
                  reconciliation_note="", evidence_ids=["ev-osv-m1"])],
        alert=alert,
    )
    result = correctness(traj, gold, snap)
    assert result["score"] == 1.0, "an excluded (unscoreable) alert was graded"
    assert any("excluded" in f for f in result["fails"]) or not result["fails"]


def test_missing_verdict_still_counts_as_wrong():
    """The gold-denominator property must survive the rewrite: an arm cannot inflate
    correctness by skipping a scoreable alert."""
    gold, snap = _disagree_gold()
    traj = _trajectory([], alert=DISAGREE_ALERT)
    result = correctness(traj, gold, snap)
    assert result["score"] == 0.0
    assert any("no verdict" in f for f in result["fails"])


def test_no_published_number_moves():
    """Pure honesty fix: routing through verify_verdict must not change any v0.1
    figure on the deterministic arm."""
    snap = Snapshot()
    per = [score_trajectory(run_graph(i, snap, system_variant="deterministic_script"),
                            build_gold(i, snap), snap)
           for i in SEED_INPUTS.values()]
    agg = aggregate(per)
    assert agg["correctness"] == 1.0
    assert agg["groundedness"] == 1.0


def test_score_trajectory_requires_a_snapshot():
    """Both call sites (ablation.py, run_eval.py) already hold one; the signature
    change is what forces correctness onto the real verifier."""
    snap = Snapshot()
    inp = next(iter(SEED_INPUTS.values()))
    traj = run_graph(inp, snap, system_variant="deterministic_script")
    with pytest.raises(TypeError):
        score_trajectory(traj, build_gold(inp, snap))


def test_baseline_committed_aggregate_is_unchanged():
    baseline = json.loads((REPO / "golden" / "baseline.json").read_text())
    agg = baseline["deterministic_script"]["aggregate"]
    assert agg["correctness"] == 1.0 and agg["groundedness"] == 1.0
