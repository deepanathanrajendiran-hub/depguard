"""D9 — the ablation harness, exercised WITHOUT an LLM key.

The script arm always runs; the LLM arms are pending (no key). We assert the harness shape,
the script arm's by-construction perfect correctness/groundedness, byte-reproducibility of
the metric numbers, and that no LLM number is fabricated when the arms did not run.
"""

from __future__ import annotations

from depguard.ablation import available_arms, format_markdown, run_ablation
from depguard.snapshot import Snapshot
from golden.seeds import SEED_INPUTS

# a small, fixed subset keeps the test fast; the harness itself iterates all seeds.
SUBSET = {k: SEED_INPUTS[k] for k in
          ("seed_01", "tp_lodash", "withdrawn_minimist", "nofix_ip", "multi_tar")}


def test_available_arms_gate_on_key():
    assert available_arms({}) == ["deterministic_script"]
    assert available_arms({"LLM_API_KEY": "x"}) == \
        ["deterministic_script", "single_agent", "multi_agent"]


def test_script_only_ablation_shape_and_by_construction():
    snap = Snapshot()
    res = run_ablation(SUBSET, snap, arms=["deterministic_script"])
    assert res["arms_run"] == ["deterministic_script"]
    assert res["arms_pending"] == ["single_agent", "multi_agent"]
    agg = res["aggregates"]["deterministic_script"]
    # script arm == oracle by construction
    assert agg["correctness"] == 1.0
    assert agg["groundedness"] == 1.0
    # only one arm ⇒ no pairwise CI, flip count is honestly pending (NOT 0/fabricated)
    assert res["pairwise_ci"] == {}
    assert res["flip_count_multi_vs_single"] is None
    assert res["corpus_snapshot_id"].startswith("depguard-corpus-")


def test_ablation_metrics_are_byte_reproducible():
    snap = Snapshot()
    a = run_ablation(SUBSET, snap, arms=["deterministic_script"])
    b = run_ablation(SUBSET, snap, arms=["deterministic_script"])
    # metric aggregates + any CIs are deterministic (latency is excluded / report-only)
    assert a["aggregates"] == b["aggregates"]
    assert a["pairwise_ci"] == b["pairwise_ci"]
    assert a["verdict_flip_matrix"] == b["verdict_flip_matrix"]


def test_ablation_persists_audit_trail_and_zero_usage_for_script_arm():
    """The raw trajectories + per-trajectory metric rows are the audit trail (D9 review #3),
    and the keyless script arm records zero LLM usage / zero fallbacks (D9 review #2/#5)."""
    snap = Snapshot()
    res = run_ablation(SUBSET, snap, arms=["deterministic_script"])
    assert set(res["_trajectories"]["deterministic_script"]) == set(SUBSET)
    rows = res["_metric_rows"]["deterministic_script"]
    assert len(rows) == len(SUBSET)
    assert all("seed" in r and "correctness" in r for r in rows)
    u = res["llm_usage"]["deterministic_script"]
    assert u["calls"] == 0 and u["total_tokens"] == 0 and u["fallbacks"] == 0
    assert res["planner_fallbacks"]["deterministic_script"] == 0


def test_markdown_flags_pending_llm_arms():
    snap = Snapshot()
    res = run_ablation(SUBSET, snap, arms=["deterministic_script"])
    md = format_markdown(res)
    assert "pending" in md.lower()
    assert "LLM_API_KEY" in md
    assert "single_agent" in md and "multi_agent" in md
    # no invented pairwise number when only one arm ran
    assert "excludes 0" in md  # legend present
