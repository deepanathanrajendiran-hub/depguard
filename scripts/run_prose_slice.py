#!/usr/bin/env python3
"""The prose-slice ablation (DECISIONS.md §5.1, v1.2.0).

The v0.1 ablation compared arms on a task engineered to be mechanically decidable, so
`deterministic_script` scored 1.0000 by construction and the LLM arms could at best tie.
They tied. That result carried no information: the ceiling was a tie before any code ran.

This harness runs the SAME corpus with the machine-readable ranges redacted, leaving the
affected range only in the advisory prose. The deterministic pipeline provably cannot
decide a redacted record — `oracle.record_containment` raises — so the arms can finally
separate. Scoring stays 100% mechanical: P5 compares containment bitvectors over the
frozen published list using the same `record_containment` on both sides.

Arms:
    deterministic_script  no prose parser exists; abstains by construction
    regex_baseline        the strongest honest non-LLM baseline (no API key needed)
    llm_extractor         the model under test

Usage:
    python scripts/run_prose_slice.py                 # all arms; LLM arm needs a key
    python scripts/run_prose_slice.py --repeats 3     # LLM arm 3x, report the spread
    python scripts/run_prose_slice.py --no-llm        # keyless: script + regex only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from depguard.extractors import null_extractor, regex_extractor  # noqa: E402
from depguard.llm_extractor import llm_extractor  # noqa: E402
from depguard.llm_meter import METER  # noqa: E402
from depguard.redact import gold_abstains, prose_of  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402
from depguard.stats import compare_arms  # noqa: E402
from depguard.tools.external import resolve_published_versions  # noqa: E402
from depguard.verifier import verify_range_reconstruction  # noqa: E402

OUT_JSON = REPO / "results" / "prose_slice.json"
OUT_MD = REPO / "results" / "prose_slice.md"


def build_seeds(snapshot: Snapshot) -> list[dict]:
    """One seed per (advisory, package) pair that has a frozen published-version list.
    Deterministic: path-sorted, and the corpus is frozen."""
    seeds = []
    for path in sorted((REPO / "corpus" / "osv").rglob("*.json")):
        record = json.loads(path.read_text())
        ecosystem = path.parent.name
        for entry in record.get("affected", []):
            if entry["package"]["ecosystem"] != ecosystem:
                continue
            name = entry["package"]["name"]
            resolved = resolve_published_versions(ecosystem, name, snapshot=snapshot)
            published = resolved["data"]["versions"] if resolved["ok"] else []
            if published:
                seeds.append({
                    "seed": f"{record['id']}::{name}",
                    "advisory_id": record["id"],
                    "ecosystem": ecosystem,
                    "name": name,
                    "record": record,
                    "published": published,
                    "gold_abstain": gold_abstains(record),
                })
            break  # one package per advisory keeps the seed set balanced
    return seeds


def run_arm(seeds, extractor, *, pass_name=False) -> dict:
    rows = []
    started = time.perf_counter()
    for seed in seeds:
        prose = prose_of(seed["record"])
        kwargs = {"name": seed["name"]} if pass_name else {}
        try:
            proposal = extractor(prose, seed["published"], seed["ecosystem"], **kwargs)
        except Exception as exc:  # an arm that crashes scores 0, it does not abort the run
            proposal = None
            crash = f"{type(exc).__name__}: {exc}"
        else:
            crash = None
        score = verify_range_reconstruction(
            proposal, ecosystem=seed["ecosystem"], name=seed["name"],
            true_record=seed["record"], published_versions=seed["published"],
        )
        rows.append({
            "seed": seed["seed"],
            "ecosystem": seed["ecosystem"],
            "gold_abstain": seed["gold_abstain"],
            "status": score.status,
            "passed": score.passed,
            "n_versions": score.n_versions,
            "n_mismatch": score.n_mismatch,
            "mismatches": [list(m) for m in score.mismatches],
            "proposal": proposal,
            "crash": crash,
        })
    scored = [r for r in rows if r["status"] != "excluded"]
    return {
        "rows": rows,
        "per_seed": [1.0 if r["passed"] else 0.0 for r in scored],
        "seeds_scored": [r["seed"] for r in scored],
        "range_accuracy": (sum(bool(r["passed"]) for r in scored) / len(scored))
        if scored else 0.0,
        "n_scored": len(scored),
        "n_correct": sum(bool(r["passed"]) for r in scored),
        "wrong_abstain": sum(1 for r in scored
                             if r["status"] == "abstained" and not r["passed"]),
        "wrong_range": sum(1 for r in scored
                           if r["status"] == "scored" and not r["passed"]),
        "latency_s": round(time.perf_counter() - started, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1,
                    help="repeat the LLM arm N times and report the spread (default 1)")
    ap.add_argument("--no-llm", action="store_true", help="skip the LLM arm entirely")
    args = ap.parse_args()

    import os
    snapshot = Snapshot()
    seeds = build_seeds(snapshot)
    n_abstain = sum(1 for s in seeds if s["gold_abstain"])
    print(f"prose slice: {len(seeds)} seeds ({n_abstain} gold-abstain), "
          f"snapshot {snapshot.snapshot_id}")

    arms: dict = {}
    METER.reset()
    arms["deterministic_script"] = run_arm(seeds, null_extractor)
    arms["deterministic_script"]["meter"] = METER.snapshot()
    print(f"  deterministic_script : {arms['deterministic_script']['range_accuracy']:.4f}")

    METER.reset()
    arms["regex_baseline"] = run_arm(seeds, regex_extractor)
    arms["regex_baseline"]["meter"] = METER.snapshot()
    print(f"  regex_baseline       : {arms['regex_baseline']['range_accuracy']:.4f}")

    if not args.no_llm and os.environ.get("LLM_API_KEY"):
        runs = []
        for i in range(args.repeats):
            METER.reset()
            run = run_arm(seeds, llm_extractor, pass_name=True)
            run["meter"] = METER.snapshot()
            runs.append(run)
            print(f"  llm_extractor run {i + 1}/{args.repeats} : "
                  f"{run['range_accuracy']:.4f}  ({run['latency_s']}s, "
                  f"${run['meter'].get('cost_usd', 0):.4f})")
        best = max(range(len(runs)), key=lambda i: runs[i]["range_accuracy"])
        arms["llm_extractor"] = dict(
            runs[0],
            repeats=[r["range_accuracy"] for r in runs],
            repeat_runs=runs,
            range_accuracy_mean=sum(r["range_accuracy"] for r in runs) / len(runs),
            range_accuracy_min=min(r["range_accuracy"] for r in runs),
            range_accuracy_max=max(r["range_accuracy"] for r in runs),
            best_run_index=best,
        )
    elif not args.no_llm:
        print("  llm_extractor        : SKIPPED (LLM_API_KEY not set)")

    # Pairwise deltas on the shared seed order
    order = arms["deterministic_script"]["seeds_scored"]
    comparisons = {}
    names = list(arms)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sa = _aligned(arms[a], order)
            sb = _aligned(arms[b], order)
            comparisons[f"{a} - {b}"] = compare_arms(sa, sb)

    result = {
        "corpus_snapshot_id": snapshot.snapshot_id,
        "n_seeds": len(seeds),
        "n_gold_abstain": n_abstain,
        "repeats": args.repeats,
        "arms": {k: {kk: vv for kk, vv in v.items() if kk not in ("rows", "repeat_runs")}
                 for k, v in arms.items()},
        "comparisons": comparisons,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n")
    (REPO / "results" / "prose_slice_rows.json").write_text(
        json.dumps({k: v["rows"] for k, v in arms.items()}, indent=2) + "\n")
    OUT_MD.write_text(format_markdown(result))
    print(f"\nwrote {OUT_JSON.relative_to(REPO)} and {OUT_MD.relative_to(REPO)}")
    return 0


def _aligned(arm: dict, order: list[str]) -> list[float]:
    by_seed = dict(zip(arm["seeds_scored"], arm["per_seed"]))
    return [by_seed.get(s, 0.0) for s in order]


def format_markdown(result: dict) -> str:
    from depguard.ablation import _fmt_ci

    lines = [
        "# Prose slice — where the deterministic script provably cannot compete",
        "",
        f"`corpus_snapshot_id = {result['corpus_snapshot_id']}` · "
        f"{result['n_seeds']} seeds ({result['n_gold_abstain']} gold-abstain)",
        "",
        "The v0.1 ablation ran on a mechanically decidable task, so the script scored",
        "1.0000 by construction and the LLM arms could at best tie. Here the affected",
        "range is redacted out of the frozen records and survives only in the advisory",
        "prose, which no grammar recovers. `record_containment` RAISES on a redacted",
        "record, so the script's failure is a raised exception, not a contested number.",
        "",
        "Scoring is P5 SEMANTIC-RANGE-EQUIVALENCE and stays 100% mechanical: the claim is",
        "materialised against the frozen published-version list and compared to the",
        "unredacted record by containment bitvector, running the SAME",
        "`record_containment` on both sides. No LLM judge anywhere.",
        "",
        "## Per-arm range accuracy",
        "",
        "| arm | range accuracy | correct | scored | wrong abstain | wrong range | latency (s) | LLM calls | cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, arm in result["arms"].items():
        meter = arm.get("meter", {})
        acc = arm.get("range_accuracy_mean", arm["range_accuracy"])
        cell = f"{acc:.4f}"
        if "range_accuracy_min" in arm:
            cell += f" [{arm['range_accuracy_min']:.4f}–{arm['range_accuracy_max']:.4f}]"
        lines.append(
            f"| {name} | {cell} | {arm['n_correct']} | {arm['n_scored']} | "
            f"{arm['wrong_abstain']} | {arm['wrong_range']} | {arm['latency_s']} | "
            f"{meter.get('calls', 0)} | ${meter.get('cost_usd', 0):.4f} |"
        )
    if result["repeats"] > 1:
        lines += ["", f"_LLM arm run {result['repeats']}x; the bracket is the min–max "
                      "spread across runs, not a confidence interval._"]

    lines += ["", "## Pairwise deltas (paired bootstrap, 10k resamples, 95% CI)", "",
              "| comparison | Δ range accuracy |", "| --- | --- |"]
    for label, ci in result["comparisons"].items():
        lines.append(f"| `{label}` | {_fmt_ci(ci)} |")
    lines += ["", "`*` marks an interval excluding 0.", ""]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
