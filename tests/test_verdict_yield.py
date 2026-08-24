"""`action_advancement` was an inverted metric; `verdict_yield` replaces it.

`action_advancement` was |steps that advanced a new alert| / |executed steps|. On a
one-alert-per-trajectory corpus the numerator is always 0 or 1, so the metric reduces to
`1 / n_executed_steps` — it scores an arm HIGHER for doing fewer steps. Measured on the
shipped v0.1 `single_agent` rows:

    action_advancement   n   mean correctness
    0.2500 (best)        9   0.333  (worst)
    0.1667              13   0.538
    0.1429 (worst)       6   1.000  (perfect)
    0.0000               1   0.000

within-arm corr(action_advancement, correctness) = -0.172, and results/ablation_v01.md
consequently marked the *deterministic* arm "significantly worse" on it than the arm
that answered 13 of 29 alerts wrong.

`verdict_yield` = |distinct alerts given a verdict| / |alerts|. Monotone with outcome
quality, bounded in [0,1], and it makes abandonment visible instead of rewarding it.
"""

import json
from pathlib import Path

import pytest

from depguard.graph import build_gold, run_graph
from depguard.metrics import METRICS, aggregate, score_trajectory, verdict_yield
from depguard.snapshot import Snapshot
from golden.seeds import SEED_INPUTS

REPO = Path(__file__).resolve().parent.parent
SNAP = Snapshot()


def _traj(n_alerts, verdicted_ids, *, executed_steps=6):
    return {
        "input": {"alerts": [{"alert_id": f"a{i}"} for i in range(n_alerts)]},
        "verdicts": [{"alert_id": a} for a in verdicted_ids],
        "plan": [{"status": "executed", "produced_verdict_for": None}
                 for _ in range(executed_steps)],
    }


def test_action_advancement_is_gone():
    assert "action_advancement" not in METRICS
    assert "verdict_yield" in METRICS


def test_full_yield_when_every_alert_is_answered():
    assert verdict_yield(_traj(3, ["a0", "a1", "a2"]))["score"] == 1.0


def test_abandonment_lowers_the_score():
    """THE tp_axios shape: a run that answers nothing scores 0, not 'best in show'."""
    assert verdict_yield(_traj(1, []))["score"] == 0.0
    assert verdict_yield(_traj(3, ["a0"]))["score"] == pytest.approx(1 / 3)


def test_score_does_not_depend_on_how_many_steps_were_executed():
    """The inversion killer: doing MORE work must never lower the score."""
    thorough = verdict_yield(_traj(1, ["a0"], executed_steps=7))["score"]
    lazy = verdict_yield(_traj(1, ["a0"], executed_steps=4))["score"]
    assert thorough == lazy == 1.0


def test_duplicate_verdicts_do_not_inflate_beyond_one():
    assert verdict_yield(_traj(2, ["a0", "a0", "a0"]))["score"] == 0.5


def test_verdicts_for_unknown_alerts_are_not_counted():
    assert verdict_yield(_traj(2, ["a0", "ghost"]))["score"] == 0.5


def test_deterministic_arm_scores_a_perfect_yield():
    """The arm that answers every alert should top this metric — it did not top
    action_advancement, which is the whole reason for the change."""
    per = [score_trajectory(run_graph(i, SNAP, system_variant="deterministic_script"),
                            build_gold(i, SNAP), SNAP)
           for i in SEED_INPUTS.values()]
    assert aggregate(per)["verdict_yield"] == 1.0


def test_baseline_no_longer_pins_the_retired_metric():
    baseline = json.loads((REPO / "golden" / "baseline.json").read_text())
    agg = baseline["deterministic_script"]["aggregate"]
    assert "action_advancement" not in agg
    assert agg["verdict_yield"] == 1.0
