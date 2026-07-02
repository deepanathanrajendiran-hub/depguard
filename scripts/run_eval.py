#!/usr/bin/env python3
"""The merge-blocking eval (DECISIONS.md §4.1 metrics; DEPGUARD_V01_PLAN D7).

Runs the graph over every golden input and scores it with the mechanical metrics.
The gate is keyed to the **deterministic_script arm**: fully reproducible, no API key,
so it blocks merges the moment any core regresses (tools, oracle, verifier, evidence,
graph structure, metrics). The deterministic arm MUST hold correctness == groundedness
== 1.0 and every aggregate metric >= the committed baseline.

If `LLM_API_KEY` is set, the **multi_agent arm** additionally runs and must not drop
correctness/groundedness below baseline — this is the arm a planner-prompt regression
would move. It is intentionally NOT the primary blocker: an LLM arm is non-deterministic
and a flaky merge-gate is an anti-pattern; the scarce asset (the mechanical oracle) is
what the deterministic arm pins.

Usage:
  python scripts/run_eval.py baseline   # (re)write golden/baseline.json from an honest run
  python scripts/run_eval.py check       # gate: compare a fresh run to the baseline
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from depguard.graph import build_gold, run_graph  # noqa: E402
from depguard.metrics import METRICS, aggregate, score_trajectory  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402
from golden.seeds import SEED_INPUTS  # noqa: E402

BASELINE = REPO / "golden" / "baseline.json"
EPS = 1e-9


def run_arm(snap, variant):
    out = []
    for name, inp in SEED_INPUTS.items():
        traj = run_graph(inp, snap, system_variant=variant)
        out.append((name, score_trajectory(traj, build_gold(inp, snap))))
    return out


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    snap = Snapshot()
    per = run_arm(snap, "deterministic_script")
    agg = aggregate([s for _, s in per])

    if mode == "baseline":
        BASELINE.write_text(json.dumps({
            "corpus_snapshot_id": snap.snapshot_id,
            "n_trajectories": len(per),
            "deterministic_script": {"aggregate": agg},
            "note": "Honest first-run numbers — never rounded up. action_advancement is "
                    "the structural ratio of verdict-producing steps to all executed "
                    "steps (§4.1.2); it is not an error. NO ablation/comparison numbers "
                    "here — those arrive in D8–D9 (out of v0.1 D7 scope).",
        }, indent=2) + "\n")
        print("wrote baseline:", {k: round(v, 4) for k, v in agg.items()})
        return 0

    baseline = json.loads(BASELINE.read_text())["deterministic_script"]["aggregate"]
    failed = []
    for m in METRICS:
        if agg[m] < baseline[m] - EPS:
            failed.append(f"aggregate {m}: {agg[m]:.4f} < baseline {baseline[m]:.4f}")
    for name, s in per:
        if s["correctness"]["score"] < 1.0:
            failed.append(f"{name}: correctness {s['correctness']['score']:.2f} "
                          f"{s['correctness']['fails']}")
        if s["groundedness"]["score"] < 1.0:
            failed.append(f"{name}: groundedness {s['groundedness']['score']:.2f} "
                          f"{s['groundedness']['fails']}")

    if os.environ.get("LLM_API_KEY"):
        from depguard.llm_meter import METER
        METER.reset()
        try:
            lper = run_arm(snap, "multi_agent")
        except Exception as exc:  # noqa: BLE001 — key present ⇒ a crashing arm is a HARD failure
            failed.append(f"multi_agent arm crashed (key is set): {exc!r}")
        else:
            lagg = aggregate([s for _, s in lper])
            fb = METER.snapshot()["fallbacks"]
            print("multi_agent aggregate:", {k: round(v, 4) for k, v in lagg.items()},
                  f"(planner_fallbacks={fb})")
            # metric dips stay non-blocking (LLM noise ≠ regression), but a crash does not.
            for m in ("correctness", "groundedness"):
                if lagg[m] < baseline[m] - 1e-3:
                    failed.append(f"multi_agent {m}: {lagg[m]:.4f} < baseline {baseline[m]:.4f}")

    if failed:
        print("EVAL GATE FAILED:")
        for f in failed:
            print("  -", f)
        return 1
    print(f"EVAL GATE PASSED ({len(per)} trajectories). deterministic aggregate:",
          {k: round(v, 4) for k, v in agg.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
