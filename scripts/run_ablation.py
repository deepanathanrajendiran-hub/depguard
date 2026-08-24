#!/usr/bin/env python3
"""Run the three-arm ablation → results/ablation_v01.{json,md}.

The deterministic_script arm always runs (no key). The single_agent and multi_agent LLM
arms run ONLY when LLM_API_KEY is set — otherwise they are reported as `pending` and NO LLM
number is written (house rule: no un-measured number anywhere). To produce the full
headline table, set LLM_API_KEY (+ optional LLM_BASE_URL / LLM_MODEL) and re-run.

Run:  python scripts/run_ablation.py
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from depguard.ablation import available_arms, format_markdown, run_ablation  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402
from golden.seeds import SEED_INPUTS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1,
                    help="repeat the LLM arms N times and report the spread. The "
                         "deterministic arm is bit-reproducible, so it always runs once. "
                         "n=1 makes every LLM claim an observation rather than a "
                         "propensity, which is why v0.1's single-agent findings needed "
                         "this flag.")
    args = ap.parse_args()

    snap = Snapshot()
    arms = available_arms(os.environ)
    result = run_ablation(SEED_INPUTS, snap, arms=arms)

    llm_arms = [a for a in arms if a != "deterministic_script"]
    if args.repeats > 1 and llm_arms:
        repeats = {a: [result["aggregates"][a]["correctness"]] for a in llm_arms}
        ground = {a: [result["aggregates"][a]["groundedness"]] for a in llm_arms}
        for i in range(args.repeats - 1):
            print(f"  repeat {i + 2}/{args.repeats} ...", flush=True)
            extra = run_ablation(SEED_INPUTS, snap, arms=llm_arms)
            for a in llm_arms:
                repeats[a].append(extra["aggregates"][a]["correctness"])
                ground[a].append(extra["aggregates"][a]["groundedness"])
        result["repeats"] = {
            a: {
                "n": args.repeats,
                "correctness": repeats[a],
                "correctness_mean": statistics.fmean(repeats[a]),
                "correctness_min": min(repeats[a]),
                "correctness_max": max(repeats[a]),
                "groundedness": ground[a],
                "groundedness_mean": statistics.fmean(ground[a]),
                "groundedness_min": min(ground[a]),
                "groundedness_max": max(ground[a]),
            }
            for a in llm_arms
        }
        print("  repeat spread:")
        for a in llm_arms:
            r = result["repeats"][a]
            print(f"    {a}: correctness {r['correctness_mean']:.4f} "
                  f"[{r['correctness_min']:.4f}-{r['correctness_max']:.4f}] "
                  f"over {args.repeats} runs")

    outdir = REPO / "results"
    outdir.mkdir(exist_ok=True)
    # markdown keeps measured wall-clock latency + token/cost; JSON drops the underscore-
    # prefixed heavy/report-only keys so the committed summary stays focused.
    (outdir / "ablation_v01.md").write_text(format_markdown(result))
    json_result = {k: v for k, v in result.items() if not k.startswith("_")}
    (outdir / "ablation_v01.json").write_text(json.dumps(json_result, indent=2) + "\n")

    # audit trail (the trajectories ARE the product): raw per-arm trajectories + the
    # per-trajectory metric rows that back every aggregate, so both are checkable post-hoc.
    tdir = outdir / "trajectories"
    tdir.mkdir(exist_ok=True)
    for arm, trajs in result["_trajectories"].items():
        (tdir / f"{arm}.jsonl").write_text(
            "".join(json.dumps(trajs[n]) + "\n" for n in sorted(trajs)))
    (outdir / "metric_rows.json").write_text(
        json.dumps(result["_metric_rows"], indent=2) + "\n")

    print(f"arms run: {', '.join(arms)}")
    if result["arms_pending"]:
        print(f"arms PENDING (need LLM_API_KEY): {', '.join(result['arms_pending'])}")
    for arm in arms:
        agg = result["aggregates"][arm]
        u = result["llm_usage"][arm]
        print(f"  {arm}: correctness={agg['correctness']:.4f} "
              f"groundedness={agg['groundedness']:.4f} "
              f"tool_selection={agg['tool_selection']:.4f} "
              f"latency={result['_latency_seconds'][arm]:.2f}s "
              f"calls={u['calls']} tokens={u['total_tokens']} "
              f"cost=${u['cost_usd']:.4f} fallbacks={u['fallbacks']}")
    fc = result["flip_count_multi_vs_single"]
    print(f"flip count (multi vs single): {'pending' if fc is None else fc}")
    total_fb = sum(result["planner_fallbacks"].values())
    print(f"TOTAL PLANNER FALLBACKS: {total_fb}"
          + ("  <-- WARNING: multi_agent numbers contaminated" if total_fb else "  (clean)"))
    print(f"wrote {outdir/'ablation_v01.json'}, .md, trajectories/, metric_rows.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
