#!/usr/bin/env python3
"""Run the three-arm ablation → results/ablation_v01.{json,md} (docs/HANDOFF_D8-D14.md §D9).

The deterministic_script arm always runs (no key). The single_agent and multi_agent LLM
arms run ONLY when LLM_API_KEY is set — otherwise they are reported as `pending` and NO LLM
number is written (house rule: no un-measured number anywhere). To produce the full
headline table, set LLM_API_KEY (+ optional LLM_BASE_URL / LLM_MODEL) and re-run.

Run:  python scripts/run_ablation.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from depguard.ablation import available_arms, format_markdown, run_ablation  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402
from golden.seeds import SEED_INPUTS  # noqa: E402


def main() -> int:
    snap = Snapshot()
    arms = available_arms(os.environ)
    result = run_ablation(SEED_INPUTS, snap, arms=arms)

    outdir = REPO / "results"
    outdir.mkdir(exist_ok=True)
    # markdown keeps the measured wall-clock latency; JSON drops it so the committed
    # artifact stays byte-stable (only the deterministic metric/CI numbers).
    (outdir / "ablation_v01.md").write_text(format_markdown(result))
    json_result = {k: v for k, v in result.items() if k != "_latency_seconds"}
    (outdir / "ablation_v01.json").write_text(json.dumps(json_result, indent=2) + "\n")

    print(f"arms run: {', '.join(arms)}")
    if result["arms_pending"]:
        print(f"arms PENDING (need LLM_API_KEY): {', '.join(result['arms_pending'])}")
    for arm in arms:
        agg = result["aggregates"][arm]
        print(f"  {arm}: correctness={agg['correctness']:.4f} "
              f"groundedness={agg['groundedness']:.4f} "
              f"tool_selection={agg['tool_selection']:.4f} "
              f"latency={result['_latency_seconds'][arm]:.2f}s")
    fc = result["flip_count_multi_vs_single"]
    print(f"flip count (multi vs single): {'pending' if fc is None else fc}")
    print(f"wrote {outdir/'ablation_v01.json'} and {outdir/'ablation_v01.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
