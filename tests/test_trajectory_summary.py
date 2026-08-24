"""Fail-unsafe regression: `verdicts_summary` must never dismiss an alert the run
never answered.

The v0.1 ablation shipped a real instance of this. `single_agent` on seed `tp_axios`
abandoned with 0 tool calls, 0 evidence and 0 verdicts, yet its trajectory emitted
`{n_alerts: 1, n_true_positive: 0, n_false_positive: 1}` against a gold of
`affected=True` — a genuine CVE reported as a dismissed false positive by a run that
did no work. The old `build()` computed `n_false_positive = n_alerts - n_tp`, so every
unanswered alert silently became a false positive.

The summary is now derived from EMITTED verdicts only, and the gap between alerts and
verdicts is reported explicitly as `n_unresolved`. Silence is no longer an all-clear.
"""

import json
from pathlib import Path

import pytest

from depguard.trajectory import TrajectoryBuilder

REPO = Path(__file__).resolve().parent.parent


def _builder(n_alerts: int) -> TrajectoryBuilder:
    alerts = [
        {
            "alert_id": f"a{i}",
            "ecosystem": "npm",
            "name": "lodash",
            "pinned_version": "4.17.20",
            "advisory_id": "GHSA-35jh-r3h4-6jhm",
            "source": "scanner",
        }
        for i in range(n_alerts)
    ]
    manifest = [{
        "ecosystem": "npm",
        "name": "lodash",
        "pinned_version": "4.17.20",
        "purl": "pkg:npm/lodash@4.17.20",
    }]
    return TrajectoryBuilder(
        system_variant="deterministic_script",
        model_route="none",
        corpus_snapshot_id="depguard-corpus-2026-07-01-c6f3471a2245",
        trajectory_input={"manifest": manifest, "alerts": alerts},
    )


def _verdict(alert_id: str, affected: bool) -> dict:
    return {
        "alert_id": alert_id,
        "affected": affected,
        "minimal_fixed_version": "4.17.21" if affected else None,
        "withdrawn": False,
        "cvss3_score": None,
        "evidence_ids": [f"ev-osv-{alert_id}"],
        "source_agreement": "agree",
        "reconciliation_note": "",
    }


def test_abandoned_run_reports_zero_false_positives_not_one():
    """THE tp_axios BUG. A run that emits no verdict must not dismiss the alert."""
    summary = _builder(1).build()["final_answer"]["verdicts_summary"]
    assert summary["n_alerts"] == 1
    assert summary["n_true_positive"] == 0
    assert summary["n_false_positive"] == 0, (
        "an alert with no verdict was counted as a false positive — fail-unsafe"
    )
    assert summary["n_unresolved"] == 1


def test_unresolved_is_the_gap_between_alerts_and_verdicts():
    b = _builder(3)
    b.add_verdict(_verdict("a0", True))
    b.add_verdict(_verdict("a1", False))
    summary = b.build()["final_answer"]["verdicts_summary"]
    assert summary == {
        "n_alerts": 3,
        "n_true_positive": 1,
        "n_false_positive": 1,
        "n_unresolved": 1,
    }


def test_fully_answered_run_has_no_unresolved():
    b = _builder(2)
    b.add_verdict(_verdict("a0", True))
    b.add_verdict(_verdict("a1", False))
    summary = b.build()["final_answer"]["verdicts_summary"]
    assert summary["n_unresolved"] == 0
    assert summary["n_true_positive"] + summary["n_false_positive"] == summary["n_alerts"]


def test_counts_always_partition_the_alert_set():
    """tp + fp + unresolved == n_alerts, for every arm, always."""
    for emitted in range(4):
        b = _builder(3)
        for i in range(emitted):
            b.add_verdict(_verdict(f"a{i}", i % 2 == 0))
        s = b.build()["final_answer"]["verdicts_summary"]
        assert s["n_true_positive"] + s["n_false_positive"] + s["n_unresolved"] == s["n_alerts"]


@pytest.mark.parametrize("arm", ["deterministic_script", "single_agent", "multi_agent"])
def test_no_committed_trajectory_dismisses_an_unanswered_alert(arm):
    """Guards the shipped artefacts, not just the builder: no trajectory in
    results/ may claim a false positive it never emitted a verdict for."""
    path = REPO / "results" / "trajectories" / f"{arm}.jsonl"
    if not path.exists():
        pytest.skip(f"{path.name} not regenerated yet")
    rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    if any("n_unresolved" not in r["final_answer"]["verdicts_summary"] for r in rows):
        pytest.skip(
            f"{path.name} predates the fail-safe-counting fix (no n_unresolved); "
            "this guard activates automatically once scripts/run_ablation.py is re-run"
        )
    for t in rows:
        s = t["final_answer"]["verdicts_summary"]
        n_emitted = len(t["verdicts"])
        assert s["n_true_positive"] + s["n_false_positive"] == n_emitted, (
            f"{t['trajectory_id']}: summary counts {s['n_true_positive'] + s['n_false_positive']} "
            f"verdicts but the trajectory emitted {n_emitted}"
        )
