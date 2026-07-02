"""D5 — the first end-to-end trajectory test (DECISIONS.md §8 Week-1 deliverable).

Runs the WHOLE graph offline on corpus/ for seed_01 (the headline scanner false
positive: lodash 4.17.21 flagged for CVE-2021-23337, but 4.17.21 is the fixed
release), validates the emitted §3 Trajectory against the schema, and asserts the
§5 verifier scores every verdict CORRECT with affected==False.

The primary run uses the `deterministic_script` arm (no LLM) so the graph is
mechanically verified in plain CI. A second test exercises the `multi_agent` LLM
planner and is SKIPPED when LLM_API_KEY is unset (skip, not fail) — the owner adds
the key as a GitHub Actions secret for the D7 gate.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from depguard.agreement import observe_from_extract  # noqa: E402
from depguard.graph import build_gold, run_graph  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402
from depguard.tools.external import (  # noqa: E402
    osv_query_package,
    resolve_published_versions,
)
from depguard.trajectory import TrajectoryInvalid, gold_ref_for  # noqa: E402
from depguard.verifier import verify_verdict  # noqa: E402
from golden.seeds import SEED_INPUTS  # noqa: E402

SEED = "seed_01"
INPUT = SEED_INPUTS[SEED]


def _score_all(traj, snap):
    """Score every verdict with the §5 verifier, rebuilding gold from the corpus."""
    scores = []
    by_alert = {a["alert_id"]: a for a in INPUT["alerts"]}
    for v in traj["verdicts"]:
        a = by_alert[v["alert_id"]]
        eco, name, ver = a["ecosystem"], a["name"], a["pinned_version"]
        advisories = osv_query_package(eco, name, ver, snapshot=snap)["data"]["advisories"]
        record = next(
            r for r in advisories
            if r["id"] == a["advisory_id"] or a["advisory_id"] in r.get("aliases", [])
        )
        pub = resolve_published_versions(eco, name, snapshot=snap)["data"]["versions"]
        obs = observe_from_extract(snap.read_extract(eco, name), ver)
        scores.append(verify_verdict(
            v, ecosystem=eco, name=name, pinned_version=ver,
            osv_record=record, published_versions=pub, depsdev=obs,
        ))
    return scores


# --------------------------------------------------------------------------- #
# deterministic arm — runs everywhere (this is the Week-1 deliverable check)
# --------------------------------------------------------------------------- #

def test_deterministic_graph_emits_schema_valid_trajectory():
    traj = run_graph(INPUT, Snapshot(), system_variant="deterministic_script")
    assert traj["system_variant"] == "deterministic_script"
    assert traj["gold_ref"] == gold_ref_for(INPUT)
    # every plan step executed; the 6 pipeline tools all fired ok
    assert all(s["status"] == "executed" for s in traj["plan"])
    assert [t["tool_name"] for t in traj["tool_calls"]] == [
        "parse_manifest", "osv_query_package", "resolve_published_versions",
        "check_version_affected", "compute_minimal_fix", "crosscheck_second_source",
    ]
    assert all(t["status"] == "ok" for t in traj["tool_calls"])


def test_seed_01_is_scored_correct_and_not_affected():
    snap = Snapshot()
    traj = run_graph(INPUT, snap, system_variant="deterministic_script")
    scores = _score_all(traj, snap)
    assert scores, "no verdicts scored"
    for s in scores:
        assert s.status == "scored"
        assert s.correct is True, f"verifier rejected a correct verdict: {s.predicates}"
    # the headline assertion: the false positive is called out
    assert all(v["affected"] is False for v in traj["verdicts"])


def test_predicted_verdict_equals_oracle_gold():
    """Same code labels gold and scores predictions — deterministic arm reproduces
    the oracle gold exactly (the shared-oracle invariant end-to-end)."""
    snap = Snapshot()
    traj = run_graph(INPUT, snap, system_variant="deterministic_script")
    gold = build_gold(INPUT, snap)
    assert traj["verdicts"] == gold["gold_verdicts"]


def test_committed_golden_artifacts_match_a_fresh_run():
    """golden/trajectories + golden/expected are byte-reproducible from the graph."""
    snap = Snapshot()
    traj = run_graph(INPUT, snap, system_variant="deterministic_script")
    committed_traj = json.loads((REPO / "golden" / "trajectories" / f"{SEED}.jsonl").read_text())
    committed_gold = json.loads((REPO / "golden" / "expected" / f"{SEED}.jsonl").read_text())
    assert traj == committed_traj, "regenerate with scripts/gen_golden.py"
    assert build_gold(INPUT, snap) == committed_gold


def test_gold_sidecar_shape():
    gold = json.loads((REPO / "golden" / "expected" / f"{SEED}.jsonl").read_text())
    assert set(gold) == {"gold_ref", "gold_plan_actions", "gold_plan",
                         "gold_tool_calls", "gold_verdicts"}
    assert gold["gold_plan_actions"][0] == "plan"
    assert gold["gold_plan_actions"][-1] == "emit_verdict"
    assert gold["gold_tool_calls"][0]["tool_name"] == "parse_manifest"


def test_bad_trajectory_raises_on_validation():
    """A trajectory that violates §3 must RAISE, not return silently."""
    from depguard.trajectory import TrajectoryBuilder
    b = TrajectoryBuilder(
        system_variant="deterministic_script", model_route="x",
        corpus_snapshot_id="not-a-valid-snapshot-id", trajectory_input=INPUT,
    )
    with pytest.raises(TrajectoryInvalid):
        b.build()


# --------------------------------------------------------------------------- #
# multi_agent arm — the LLM planner (skipped without a key)
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not os.environ.get("LLM_API_KEY"), reason="LLM_API_KEY unset")
def test_multi_agent_arm_matches_deterministic_verdicts():
    snap = Snapshot()
    traj = run_graph(INPUT, snap, system_variant="multi_agent")
    assert traj["system_variant"] == "multi_agent"
    scores = _score_all(traj, snap)
    for s in scores:
        assert s.correct is True
    assert all(v["affected"] is False for v in traj["verdicts"])
