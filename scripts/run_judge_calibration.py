#!/usr/bin/env python3
"""Calibrate the reconciliation-note judge against the human audit set (§4.3, v1.3.0).

§4.3 permits an LLM judge for soft narrative quality ONLY, on a published rubric, calibrated
against a 15–20 case human audit. This is that calibration.

IT IS A GATE, NOT A FORMALITY. If quadratic-weighted kappa lands below
`judge.USE_JUDGE_THRESHOLD`, this script says the judge is NOT usable and exits non-zero.
Shipping a miscalibrated judge is worse than shipping none, because its output looks like a
measurement. The threshold was fixed before the first run and is not tuned to the result.

Nothing here touches verdict correctness. `tests/test_judge_calibration.py` asserts that by
import graph, so the guarantee is structural rather than a promise in a docstring.

Usage:  python scripts/run_judge_calibration.py        (needs LLM_API_KEY)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from depguard.judge import USE_JUDGE_THRESHOLD, agreement_stats, judge_note  # noqa: E402
from depguard.llm_meter import METER  # noqa: E402

AUDIT = REPO / "golden" / "judge_audit.jsonl"
OUT = REPO / "results" / "judge_calibration.json"


def load_audit():
    rows = []
    for line in AUDIT.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "_comment" in row:
            continue
        rows.append(row)
    return rows


def main() -> int:
    if not os.environ.get("LLM_API_KEY"):
        print("LLM_API_KEY not set — calibration needs the judge model.", file=sys.stderr)
        return 2

    rows = load_audit()
    print(f"calibrating on {len(rows)} hand-labelled cases", flush=True)
    METER.reset()

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        verdicts = list(pool.map(
            lambda r: judge_note(r["note"], context=r.get("context", "")), rows))

    human = [r["human"] for r in rows]
    scores = [v["score"] for v in verdicts]
    stats = agreement_stats(human, scores)

    per_case = [
        {"id": r["id"], "human": r["human"], "judge": v["score"],
         "delta": (None if v["score"] is None else v["score"] - r["human"]),
         "trap": r.get("why", "").startswith("TRAP"), "reason": v["reason"]}
        for r, v in zip(rows, verdicts)
    ]
    usable = stats["kappa_quadratic"] >= USE_JUDGE_THRESHOLD

    print(f"\n  n scored          {stats['n']}/{len(rows)}  (unscored: {stats['unscored']})")
    print(f"  exact agreement   {stats['exact']:.4f}")
    print(f"  within 1 level    {stats['within_1']:.4f}")
    print(f"  quadratic kappa   {stats['kappa_quadratic']:.4f}  "
          f"(threshold {USE_JUDGE_THRESHOLD})")
    print(f"\n  JUDGE USABLE: {usable}")

    traps = [c for c in per_case if c["trap"]]
    if traps:
        print("\n  trap cases (a clarity judge must not reward these):")
        for c in traps:
            print(f"    {c['id']:22s} human={c['human']} judge={c['judge']}")
    worst = sorted((c for c in per_case if c["delta"] is not None),
                   key=lambda c: -abs(c["delta"]))[:5]
    print("\n  largest disagreements:")
    for c in worst:
        print(f"    {c['id']:22s} human={c['human']} judge={c['judge']} "
              f"(Δ{c['delta']:+d})")

    result = {
        "n_cases": len(rows),
        "threshold": USE_JUDGE_THRESHOLD,
        "stats": stats,
        "judge_usable": usable,
        "per_case": per_case,
        "meter": METER.snapshot(),
        "scope": "narrative clarity of reconciliation notes ONLY; never verdict correctness "
                 "(DECISIONS.md §4.3)",
        "audit_labels_provenance": "hand-assigned by the repo author against "
                                   "golden/judge_rubric.md before the judge was first run; "
                                   "single annotator, so inter-annotator agreement is "
                                   "unmeasured (see LIMITATIONS.md)",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"\nwrote {OUT.relative_to(REPO)}")
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(main())
