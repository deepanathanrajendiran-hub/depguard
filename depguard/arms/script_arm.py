"""The `deterministic_script` ablation arm.

Honest label: the **deterministic semver-containment script** — the version-range slice
osv-scanner performs WITHOUT call-graph reachability. It contains NO LLM.

Design decision (spec resolution): the deterministic pipeline the handoff describes
(parse_manifest → osv_query_package → resolve_published_versions → check_version_affected →
compute_minimal_fix → crosscheck_second_source → verdict, withdrawn override at the verdict
layer) ALREADY exists in `depguard.graph` as the graph's rule-based arm — it is also the
arm `scripts/gen_golden.py` runs to produce the committed golden set. Rather than write a
SECOND deterministic implementation that could drift from the first (and from the oracle),
this arm is a thin adapter over that one pipeline. Consequence, asserted as a test: this
arm reproduces `golden/trajectories/<seed>.jsonl` byte-for-byte. Its verdicts equal the
oracle gold BY CONSTRUCTION because every tool it calls IS the oracle the gold labeler
calls — the headline finding of the ablation, not an agent victory.
"""

from __future__ import annotations

from depguard.graph import run_graph
from depguard.snapshot import Snapshot

ARM = "deterministic_script"


def run_script_arm(trajectory_input: dict, snapshot: Snapshot) -> dict:
    """Run the deterministic semver-containment script over one triage input; return a
    schema-valid §3 Trajectory scored by the SAME verifier/metrics as the agent arms.
    No network, no LLM, no API key — runs in plain CI."""
    return run_graph(trajectory_input, snapshot, system_variant=ARM)
