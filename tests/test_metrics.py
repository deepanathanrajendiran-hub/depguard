"""D7 — the four mechanical metrics (DECISIONS.md §4.1) + correctness.

Beyond the happy path (a deterministic golden trajectory scores 1.0 where it should),
these pin the exact discriminating behaviors §4.1 mandates: spurious/missing tool
calls, redundant advancement, alert-reorder invariance vs within-alert order, and
evidence-grounding.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from depguard.graph import build_gold, run_graph  # noqa: E402
from depguard.metrics import (  # noqa: E402
    action_advancement,
    correctness,
    groundedness,
    plan_adherence,
    tool_selection,
)
from depguard.snapshot import Snapshot  # noqa: E402
from golden.seeds import SEED_INPUTS  # noqa: E402

SNAP = Snapshot()


def _real(seed="tp_lodash"):
    inp = SEED_INPUTS[seed]
    return run_graph(inp, SNAP, system_variant="deterministic_script"), build_gold(inp, SNAP)


# --------------------------- tool-selection ------------------------------- #

def test_tool_selection_perfect_on_deterministic_arm():
    traj, gold = _real()
    r = tool_selection(traj, gold)
    assert r["precision"] == 1.0 and r["recall"] == 1.0 and r["f1"] == 1.0
    assert r["fails"] == []


def test_tool_selection_spurious_call_hurts_precision():
    traj, gold = _real()
    traj["tool_calls"].append({
        "tool_name": "osv_query_package",
        "arguments": {"ecosystem": "npm", "name": "not-a-real-dep"},
    })
    r = tool_selection(traj, gold)
    assert r["recall"] == 1.0
    assert r["precision"] < 1.0
    assert any("spurious" in f for f in r["fails"])


def test_tool_selection_missing_call_hurts_recall():
    traj, gold = _real()
    traj["tool_calls"] = traj["tool_calls"][:-1]  # drop crosscheck
    r = tool_selection(traj, gold)
    assert r["precision"] == 1.0
    assert r["recall"] < 1.0
    assert any("missing" in f for f in r["fails"])


# --------------------------- action-advancement --------------------------- #

def _plan(*steps):
    out = []
    for i, (action, alert_id, status, pvf) in enumerate(steps):
        out.append({"step_index": i, "action": action, "alert_id": alert_id,
                    "rationale": "", "status": status, "produced_verdict_for": pvf})
    return out


def test_action_advancement_counts_only_new_verdicts():
    traj = {"plan": _plan(
        ("plan", None, "executed", None),
        ("emit_verdict", "a1", "executed", "a1"),
        ("emit_verdict", "a1", "executed", "a1"),  # redundant repeat — must not count
    )}
    r = action_advancement(traj)
    assert r["advancing"] == 1
    assert r["executed"] == 3
    assert any("redundant" in f for f in r["fails"])


# --------------------------- plan-adherence ------------------------------- #

CHAIN = ["retrieve_advisory", "resolve_versions", "check_containment",
         "compute_minimal_fixed", "cross_check_source", "emit_verdict"]


def _grouped_plan(order):  # order: list of alert_ids for the alert chains
    steps = [("plan", None, "executed", None), ("parse_manifest", None, "executed", None)]
    for aid in order:
        for act in CHAIN:
            steps.append((act, aid, "executed", aid if act == "emit_verdict" else None))
    return _plan(*steps)


def _gold_from(order):
    plan = [{"action": "plan", "alert_id": None},
            {"action": "parse_manifest", "alert_id": None}]
    for aid in order:
        for act in CHAIN:
            plan.append({"action": act, "alert_id": aid})
    return {"gold_plan": plan}


def test_plan_adherence_reordering_independent_alerts_scores_one():
    """The v1.1.0 whole point: processing B before A incurs NO penalty."""
    traj = {"plan": _grouped_plan(["B", "A"])}
    gold = _gold_from(["A", "B"])
    r = plan_adherence(traj, gold)
    assert r["score"] == 1.0, r["fails"]


def test_plan_adherence_within_alert_swap_scores_below_one():
    swapped = list(CHAIN)
    swapped[1], swapped[2] = swapped[2], swapped[1]  # resolve <-> check within alert A
    steps = [("plan", None, "executed", None), ("parse_manifest", None, "executed", None)]
    for act in swapped:
        steps.append((act, "A", "executed", "A" if act == "emit_verdict" else None))
    traj = {"plan": _plan(*steps)}
    gold = _gold_from(["A"])
    r = plan_adherence(traj, gold)
    assert r["score"] < 1.0
    assert any("group A" in f for f in r["fails"])


# --------------------------- groundedness + correctness ------------------- #

def test_groundedness_and_correctness_perfect_on_deterministic_arm():
    traj, gold = _real("multi_tar")  # the multi-affected witness case
    assert groundedness(traj)["score"] == 1.0
    assert correctness(traj, gold)["score"] == 1.0


def test_groundedness_flags_verdict_unsupported_by_evidence():
    traj, gold = _real("tp_lodash")
    traj["verdicts"][0]["affected"] = False  # evidence says contained → not entailed
    r = groundedness(traj)
    assert r["score"] < 1.0
    assert r["fails"]


def test_correctness_flags_wrong_verdict_vs_gold():
    traj, gold = _real("tp_lodash")
    traj["verdicts"][0]["minimal_fixed_version"] = "9.9.9"  # npm → scored field
    r = correctness(traj, gold)
    assert r["score"] < 1.0
