"""D8 — the two non-multi-agent ablation arms.

Both arms MUST emit the same schema-valid §3 Trajectory as the multi-agent graph so
one verifier + one metrics module score all three. The deterministic script arm is the
frozen reference: it reproduces the committed golden trajectories byte-for-byte (there is
ONE deterministic implementation — the graph's rule-based arm — not two that can drift).
The single-agent arm is a ReAct loop with an INJECTABLE policy so it is fully exercised in
keyless CI (the DeepSeek policy is used only when LLM_API_KEY is set, mirroring the graph).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from depguard.arms.script_arm import ARM as SCRIPT_ARM
from depguard.arms.script_arm import run_script_arm
from depguard.arms.single_agent import (
    ARM as SINGLE_ARM,
    canonical_policy,
    lazy_policy,
    run_single_agent,
)
from depguard.graph import build_gold
from depguard.metrics import correctness, groundedness, plan_adherence, tool_selection
from depguard.snapshot import Snapshot
from golden.seeds import SEED_INPUTS

REPO = Path(__file__).resolve().parent.parent
GOLDEN = REPO / "golden" / "trajectories"

SEEDS = sorted(SEED_INPUTS.items())


@pytest.fixture(scope="module")
def snap():
    return Snapshot()


# --------------------------------------------------------------------------- #
# script arm  (deterministic_script) — the frozen reference
# --------------------------------------------------------------------------- #

def test_script_arm_label():
    assert SCRIPT_ARM == "deterministic_script"


@pytest.mark.parametrize("name,inp", SEEDS, ids=[n for n, _ in SEEDS])
def test_script_arm_reproduces_committed_golden(name, inp, snap):
    """The script arm IS the golden generator's arm — its output must be byte-identical
    to golden/trajectories/<seed>.jsonl (D8 acceptance: deterministic + consistent)."""
    got = json.dumps(run_script_arm(inp, snap)) + "\n"
    want = (GOLDEN / f"{name}.jsonl").read_text()
    assert got == want


@pytest.mark.parametrize("name,inp", SEEDS[:5], ids=[n for n, _ in SEEDS[:5]])
def test_script_arm_deterministic(name, inp, snap):
    """Two runs on the same input produce identical trajectories (ids/timestamps seeded)."""
    assert run_script_arm(inp, snap) == run_script_arm(inp, snap)


def test_script_arm_variant_and_no_llm(snap):
    traj = run_script_arm(SEED_INPUTS["seed_01"], snap)
    assert traj["system_variant"] == "deterministic_script"
    assert "none" in traj["model_route"]  # NO LLM in this arm


@pytest.mark.parametrize("name,inp", SEEDS, ids=[n for n, _ in SEEDS])
def test_script_arm_scores_correct_by_construction(name, inp, snap):
    """The script arm calls the same oracle the gold labeler calls, so its verdicts are
    CORRECT and GROUNDED by construction (~100%). This is a D9 finding, asserted here."""
    traj = run_script_arm(inp, snap)
    gold = build_gold(inp, snap)
    assert correctness(traj, gold)["score"] == 1.0
    assert groundedness(traj)["score"] == 1.0


# --------------------------------------------------------------------------- #
# single-agent arm — ReAct loop, injectable policy
# --------------------------------------------------------------------------- #

def test_single_agent_label():
    assert SINGLE_ARM == "single_agent"


@pytest.mark.parametrize("name,inp", SEEDS[:5], ids=[n for n, _ in SEEDS[:5]])
def test_single_agent_validates_and_variant(name, inp, snap):
    """With the canonical policy the arm produces a schema-valid single_agent trajectory
    (build() raises on any violation)."""
    traj = run_single_agent(inp, snap, policy=canonical_policy)
    assert traj["system_variant"] == "single_agent"
    assert traj["trajectory_id"].endswith("single_agent")


@pytest.mark.parametrize("name,inp", SEEDS[:5], ids=[n for n, _ in SEEDS[:5]])
def test_single_agent_deterministic(name, inp, snap):
    assert (run_single_agent(inp, snap, policy=canonical_policy)
            == run_single_agent(inp, snap, policy=canonical_policy))


@pytest.mark.parametrize("name,inp", SEEDS, ids=[n for n, _ in SEEDS])
def test_single_agent_canonical_scores_correct(name, inp, snap):
    """The canonical policy runs the full correct tool chain, so the single-agent arm is
    also CORRECT and GROUNDED by construction (it collects the same evidence)."""
    traj = run_single_agent(inp, snap, policy=canonical_policy)
    gold = build_gold(inp, snap)
    assert correctness(traj, gold)["score"] == 1.0
    assert groundedness(traj)["score"] == 1.0


def test_single_agent_plan_is_reverse_mapped(snap):
    """Each executed tool decision maps back to a PlanAction (§0.2) so plan-adherence is
    computable; emit_verdict steps are added; there is NO run-level `plan` step (a ReAct
    agent emits no plan-as-data)."""
    traj = run_single_agent(SEED_INPUTS["seed_01"], snap, policy=canonical_policy)
    actions = [s["action"] for s in traj["plan"]]
    assert actions == [
        "parse_manifest", "retrieve_advisory", "resolve_versions",
        "check_containment", "compute_minimal_fixed", "cross_check_source", "emit_verdict",
    ]
    assert "plan" not in actions
    gold = build_gold(SEED_INPUTS["seed_01"], snap)
    pa = plan_adherence(traj, gold)
    assert 0.0 < pa["score"] <= 1.0
    # per-alert group matches gold exactly; only the control group differs (no `plan`).
    assert not any("a1" in f and "adherence" in f for f in pa["fails"])


def test_single_agent_tool_selection_recall_full(snap):
    """The canonical policy calls every gold tool with the gold scored-args ⇒ recall 1.0."""
    inp = SEED_INPUTS["seed_01"]
    traj = run_single_agent(inp, snap, policy=canonical_policy)
    gold = build_gold(inp, snap)
    assert tool_selection(traj, gold)["recall"] == 1.0


def test_single_agent_survives_malformed_alert_ids(snap):
    """A real LLM sometimes emits a per-alert tool with a null/unknown alert_id (this crashed
    the first re-run). The executor must treat it as a wasted no-op, never KeyError."""
    def bad_policy(_inp):
        return [
            {"tool": "parse_manifest", "alert_id": None},
            {"tool": "osv_query_package", "alert_id": None},        # malformed: null id
            {"tool": "osv_query_package", "alert_id": "ghost"},     # malformed: unknown id
            {"tool": "osv_query_package", "alert_id": "seed_01-a1"},  # valid
            {"tool": "check_version_affected", "alert_id": "seed_01-a1"},
            {"tool": "resolve_published_versions", "alert_id": "seed_01-a1"},
            {"tool": "compute_minimal_fix", "alert_id": "seed_01-a1"},
            {"tool": "crosscheck_second_source", "alert_id": "seed_01-a1"},
        ]

    traj = run_single_agent(SEED_INPUTS["seed_01"], snap, policy=bad_policy)  # must not raise
    assert traj["system_variant"] == "single_agent"
    # the two malformed decisions produced NO tool calls (only the 5 valid + parse_manifest)
    assert len(traj["tool_calls"]) == 6
    assert len(traj["verdicts"]) == 1  # the one real alert still gets a verdict


class _ReplayController:
    """An interactive `.next()` policy (like LLMReactPolicy) that replays a fixed decision
    list — exercises the real observe→act loop with NO API key."""

    model_route = "single_agent/replay"

    def __init__(self, decisions):
        self._q = list(decisions)

    def next(self, observation):  # noqa: ARG002 — deterministic replay ignores observation
        return self._q.pop(0) if self._q else {"tool": "__done__", "alert_id": None}


def test_single_agent_interactive_loop_matches_batch(snap):
    """Driving the interactive ReAct loop with the canonical decisions yields the SAME
    trajectory as the batch path — the observe→act machinery is covered without a key."""
    inp = SEED_INPUTS["seed_01"]
    batch = run_single_agent(inp, snap, policy=canonical_policy)
    controller = _ReplayController(canonical_policy(inp))
    interactive = run_single_agent(inp, snap, policy=controller, model_route=batch["model_route"])
    assert interactive == batch


@pytest.mark.parametrize("name,inp", SEEDS[:5], ids=[n for n, _ in SEEDS[:5]])
def test_single_agent_lazy_policy_valid_and_scoreable(name, inp, snap):
    """A worse policy (skips the cross-check step) still emits a schema-valid, fully
    scoreable trajectory — the ablation degrades gracefully, never crashes."""
    traj = run_single_agent(inp, snap, policy=lazy_policy)
    gold = build_gold(inp, snap)
    # missing cross_check ⇒ no cross_check action in the plan
    assert "cross_check_source" not in [s["action"] for s in traj["plan"]]
    # metrics still compute (scores are numbers in [0,1])
    for fn in (correctness(traj, gold), groundedness(traj), tool_selection(traj, gold)):
        assert 0.0 <= fn["score"] <= 1.0
