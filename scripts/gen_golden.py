#!/usr/bin/env python3
"""Generate committed golden artifacts from golden/seeds.py (DECISIONS.md §4.5).

For each seed input: run the deterministic-arm graph → `golden/trajectories/<seed>.jsonl`
(a schema-valid §3 Trajectory, the ablation's deterministic reference), and the oracle
gold sidecar → `golden/expected/<seed>.jsonl`. Gold is labeled by running the oracle,
never by hand. Offline (frozen corpus only).

Run:  python scripts/gen_golden.py            (from the repo root)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from depguard.graph import build_gold, run_graph  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402
from golden.seeds import SEED_INPUTS  # noqa: E402


def main() -> int:
    snap = Snapshot()
    tdir = REPO / "golden" / "trajectories"
    edir = REPO / "golden" / "expected"
    tdir.mkdir(parents=True, exist_ok=True)
    edir.mkdir(parents=True, exist_ok=True)
    for name, inp in SEED_INPUTS.items():
        traj = run_graph(inp, snap, system_variant="deterministic_script")
        (tdir / f"{name}.jsonl").write_text(json.dumps(traj) + "\n")
        gold = build_gold(inp, snap)
        (edir / f"{name}.jsonl").write_text(json.dumps(gold) + "\n")
        verdicts = [(v["alert_id"], v["affected"], v["minimal_fixed_version"])
                    for v in traj["verdicts"]]
        print(f"  {name}: {len(traj['tool_calls'])} tool calls, verdicts={verdicts}")
    print(f"generated {len(SEED_INPUTS)} golden trajectories + sidecars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
