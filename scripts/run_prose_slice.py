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
from depguard.verifier import RangeScore, verify_range_reconstruction  # noqa: E402

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


def _checkpoint(runs: list[dict]) -> None:
    """Persist after every LLM repeat. A 40-seed x N-repeat run is long enough that
    losing it to a killed shell is a real cost, and a partial result is still evidence."""
    path = REPO / "results" / "prose_slice_partial.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        [{k: v for k, v in r.items() if k != "rows"} for r in runs], indent=2) + "\n")


def _extract_one(seed, extractor, pass_name):
    kwargs = {"name": seed["name"]} if pass_name else {}
    try:
        return extractor(prose_of(seed["record"]), seed["published"],
                         seed["ecosystem"], **kwargs), None
    except Exception as exc:  # an arm that crashes scores 0, it does not abort the run
        return None, f"{type(exc).__name__}: {exc}"


def run_arm(seeds, extractor, *, pass_name=False, progress=False, workers=1) -> dict:
    """`workers` > 1 fans the extractor out across threads. The calls are I/O-bound on the
    provider, and deepseek-v4-flash is a reasoning model that spends 10k+ reasoning tokens
    (60-180 s) per seed, so a serial 40-seed x 3-repeat run takes hours. Scoring stays
    single-threaded and seed order is preserved, so results are identical to a serial run."""
    rows = []
    started = time.perf_counter()
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_extract_one, s, extractor, pass_name) for s in seeds]
            outcomes = []
            for i, fut in enumerate(futures):
                outcomes.append(fut.result())
                if progress:
                    print(f"      [{i + 1}/{len(seeds)}] {seeds[i]['seed']}", flush=True)
    else:
        outcomes = []
        for i, seed in enumerate(seeds):
            if progress:
                print(f"      [{i + 1}/{len(seeds)}] {seed['seed']}", flush=True)
            outcomes.append(_extract_one(seed, extractor, pass_name))

    for seed, (proposal, crash) in zip(seeds, outcomes):
        # A CRASH IS NOT AN ABSTENTION. verify_range_reconstruction treats proposal=None
        # as a deliberate abstain, which is scored CORRECT on a gold-abstain seed — so a
        # transport error on one of those 6 seeds would have earned the arm a point. An
        # arm that crashed did not decide anything; score it wrong outright.
        if crash is not None:
            score = RangeScore(status="crashed", passed=False,
                               gold_abstain=seed["gold_abstain"],
                               exclusion_reason=crash)
        else:
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


def _aggregate_repeats(runs: list[dict]) -> dict:
    """Combine N repeats into ONE internally consistent row.

    The first version did `dict(runs[0], ...)` and then overlaid a mean accuracy. That
    published a row whose accuracy column was a 3-run mean while its correct/scored,
    latency, calls and cost columns were run 1 — the table read `0.6417 ... 26 | 40`, but
    26/40 is 0.65, and the reported spend was a third of what was actually spent. Worse,
    the paired-bootstrap CIs were computed from run 1's per-seed vector, so a delta printed
    against the mean was really a delta against run 1. For a repo whose whole claim is
    honest measurement, that is the wrong artifact to ship.

    Now: accuracy is the mean over runs; per-seed scores are each seed's PASS RATE across
    runs (so the bootstrap resamples the arm's expected per-seed behaviour, matching the
    reported mean); counts are means; latency, calls, tokens and cost are SUMS over every
    run actually paid for."""
    order = runs[0]["seeds_scored"]
    by_seed = [dict(zip(r["seeds_scored"], r["per_seed"])) for r in runs]
    per_seed = [sum(d.get(s, 0.0) for d in by_seed) / len(runs) for s in order]
    accs = [r["range_accuracy"] for r in runs]
    meters = [r.get("meter", {}) for r in runs]

    def total(key):
        return sum(m.get(key, 0) for m in meters)

    return {
        "rows": runs[0]["rows"],
        "rows_note": "per-seed rows are from repeat 1; per-run pass vectors for every "
                     "repeat are in results/prose_slice_partial.json",
        "per_seed": per_seed,
        "seeds_scored": order,
        "range_accuracy": sum(accs) / len(accs),
        "range_accuracy_mean": sum(accs) / len(accs),
        "range_accuracy_min": min(accs),
        "range_accuracy_max": max(accs),
        "repeats": accs,
        "n_repeats": len(runs),
        "repeat_runs": runs,
        "n_scored": runs[0]["n_scored"],
        "n_correct": sum(r["n_correct"] for r in runs) / len(runs),
        "wrong_abstain": sum(r["wrong_abstain"] for r in runs) / len(runs),
        "wrong_range": sum(r["wrong_range"] for r in runs) / len(runs),
        "latency_s": round(sum(r["latency_s"] for r in runs), 2),
        "meter": {
            "calls": total("calls"), "prompt_tokens": total("prompt_tokens"),
            "completion_tokens": total("completion_tokens"),
            "total_tokens": total("total_tokens"),
            "cost_usd": sum(m.get("cost_usd", 0.0) for m in meters),
            "fallbacks": total("fallbacks"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1,
                    help="repeat the LLM arm N times and report the spread (default 1)")
    ap.add_argument("--no-llm", action="store_true", help="skip the LLM arm entirely")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent extractor calls in the LLM arm (default 8)")
    args = ap.parse_args()

    import os
    snapshot = Snapshot()
    seeds = build_seeds(snapshot)
    n_abstain = sum(1 for s in seeds if s["gold_abstain"])
    print(f"prose slice: {len(seeds)} seeds ({n_abstain} gold-abstain), "
          f"snapshot {snapshot.snapshot_id}", flush=True)

    arms: dict = {}
    METER.reset()
    arms["deterministic_script"] = run_arm(seeds, null_extractor)
    arms["deterministic_script"]["meter"] = METER.snapshot()
    print(f"  deterministic_script : {arms['deterministic_script']['range_accuracy']:.4f}", flush=True)

    METER.reset()
    arms["regex_baseline"] = run_arm(seeds, regex_extractor)
    arms["regex_baseline"]["meter"] = METER.snapshot()
    print(f"  regex_baseline       : {arms['regex_baseline']['range_accuracy']:.4f}", flush=True)

    if not args.no_llm and os.environ.get("LLM_API_KEY"):
        runs = []
        for i in range(args.repeats):
            METER.reset()
            run = run_arm(seeds, llm_extractor, pass_name=True, progress=True,
                          workers=args.workers)
            run["meter"] = METER.snapshot()
            runs.append(run)
            print(f"  llm_extractor run {i + 1}/{args.repeats} : "
                  f"{run['range_accuracy']:.4f}  ({run['latency_s']}s, "
                  f"${run['meter'].get('cost_usd', 0):.4f})", flush=True)
            _checkpoint(runs)
        arms["llm_extractor"] = _aggregate_repeats(runs)
    elif not args.no_llm:
        print("  llm_extractor        : SKIPPED (LLM_API_KEY not set)")

    # Pairwise deltas on the shared seed order
    comparisons = {}
    names = list(arms)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sa, sb = _aligned(arms[a], arms[b])
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


def _aligned(arm_a: dict, arm_b: dict) -> tuple[list[float], list[float]]:
    """Pair two arms on the seeds BOTH actually scored.

    The first version padded a missing seed with 0.0 against an order taken from
    `deterministic_script`. That arm always abstains and so never excludes anything, which
    made the padding invisible — but any seed another arm excluded (e.g.
    `no_scoreable_published_version`) was dropped from its own accuracy while counting as a
    FAILURE in the paired delta, and the padding also defeated `compare_arms`'s
    length-mismatch guard, which exists precisely to make that loud."""
    a = dict(zip(arm_a["seeds_scored"], arm_a["per_seed"]))
    b = dict(zip(arm_b["seeds_scored"], arm_b["per_seed"]))
    shared = [s for s in arm_a["seeds_scored"] if s in b]
    return [a[s] for s in shared], [b[s] for s in shared]


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
        "| arm | range accuracy | correct | scored | wrong abstain | wrong range | latency (s) | LLM calls | cost | fallbacks |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, arm in result["arms"].items():
        meter = arm.get("meter", {})
        acc = arm.get("range_accuracy_mean", arm["range_accuracy"])
        cell = f"{acc:.4f}"
        if "range_accuracy_min" in arm:
            cell += f" [{arm['range_accuracy_min']:.4f}–{arm['range_accuracy_max']:.4f}]"
        lines.append(
            f"| {name} | {cell} | {arm['n_correct']:g} | {arm['n_scored']} | "
            f"{arm['wrong_abstain']:g} | {arm['wrong_range']:g} | {arm['latency_s']} | "
            f"{meter.get('calls', 0)} | ${meter.get('cost_usd', 0):.4f} | "
            f"{meter.get('fallbacks', 0)} |"
        )
    offenders = {n: a.get("meter", {}).get("fallbacks", 0)
                 for n, a in result["arms"].items() if a.get("meter", {}).get("fallbacks")}
    if offenders:
        lines += ["", f"> **Extractor fallbacks: {offenders}.** Those seeds failed twice "
                      "and fell through to an abstain, which P5 scores WRONG on every "
                      "decidable record — so the arm's accuracy is understated by an "
                      "infrastructure failure, not a model failure. A clean result needs "
                      "0; re-run or report the count. (Same class as the v0.1 planner-"
                      "fallback counter: a number that could quietly be an artifact must "
                      "be instrumented, not assumed away.)", ""]
    if result["repeats"] > 1:
        lines += ["", f"_LLM arm run {result['repeats']}x. The bracket is the min–max "
                      "spread across runs, not a confidence interval. Accuracy and counts "
                      "are means over runs; latency, calls and cost are TOTALS over every "
                      "run actually paid for; the paired bootstrap uses each seed's pass "
                      "rate across runs, so the CI matches the mean it is printed beside._"]

    lines += ["", "## Pairwise deltas (paired bootstrap, 10k resamples, 95% CI)", "",
              "| comparison | Δ range accuracy |", "| --- | --- |"]
    for label, ci in result["comparisons"].items():
        lines.append(f"| `{label}` | {_fmt_ci(ci)} |")
    lines += ["", "`*` marks an interval excluding 0.", ""]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
