"""The three-arm ablation harness (DECISIONS.md §4.4; docs/HANDOFF_D8-D14.md §D9).

Runs each arm over the SAME golden set, scores every trajectory with the SAME metrics
module, and reports per-arm aggregates, pairwise paired-bootstrap 95% CIs, and the
verdict-flip 3×3 matrix. The deterministic_script arm always runs (no key); the two LLM
arms run ONLY when LLM_API_KEY is set (house rule 9) — otherwise they are reported as
`pending`, never fabricated (house rule: no un-measured number anywhere).

The metric scores and CIs are byte-reproducible: the script arm is deterministic and the
bootstrap seed is fixed. Wall-clock latency is measured at generation time and lives in the
markdown report only (it is environment noise, deliberately kept out of the JSON so the
committed artifact stays byte-stable).
"""

from __future__ import annotations

import itertools
import time

from depguard.arms.script_arm import run_script_arm
from depguard.arms.single_agent import run_single_agent
from depguard.graph import build_gold, run_graph
from depguard.metrics import METRICS, score_trajectory
from depguard.stats import compare_arms

LLM_ARMS = ("single_agent", "multi_agent")
ALL_ARMS = ("deterministic_script", *LLM_ARMS)
N_BOOT = 10000
BOOT_SEED = 0


def _run_multi(inp, snapshot):
    return run_graph(inp, snapshot, system_variant="multi_agent")


ARM_RUNNERS = {
    "deterministic_script": run_script_arm,
    "single_agent": run_single_agent,   # LLMReactPolicy by default (needs LLM_API_KEY)
    "multi_agent": _run_multi,
}


def available_arms(env) -> list[str]:
    """Arms runnable in the current environment: the script arm always, LLM arms iff a key
    is configured. Order is stable (script first) for deterministic reporting."""
    arms = ["deterministic_script"]
    if env.get("LLM_API_KEY"):
        arms += list(LLM_ARMS)
    return arms


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 1.0


def _flip_matrix(arms, verdicts_by_arm, alert_ids):
    """matrix[a][b] = #alerts whose actionable `affected` verdict differs between arms a,b.
    A missing verdict (an arm that skipped an alert) counts as a distinct state."""
    matrix = {a: {b: 0 for b in arms} for a in arms}
    for a, b in itertools.permutations(arms, 2):
        n = 0
        for aid in alert_ids:
            va = verdicts_by_arm[a].get(aid, "__no_verdict__")
            vb = verdicts_by_arm[b].get(aid, "__no_verdict__")
            if va != vb:
                n += 1
        matrix[a][b] = n
    return matrix


def run_ablation(seed_inputs: dict, snapshot, arms: list[str] | None = None) -> dict:
    """Run the ablation and return the structured result (the source of ablation_v01.json,
    minus wall-clock latency which the report layer adds)."""
    if arms is None:
        import os
        arms = available_arms(os.environ)
    names = sorted(seed_inputs)
    golds = {n: build_gold(seed_inputs[n], snapshot) for n in names}

    scores_by_arm: dict[str, dict[str, list[float]]] = {}
    verdicts_by_arm: dict[str, dict[str, bool]] = {}
    latency_by_arm: dict[str, float] = {}
    alert_ids: list[str] = []

    for arm in arms:
        runner = ARM_RUNNERS[arm]
        scores = {m: [] for m in METRICS}
        verdicts: dict[str, bool] = {}
        t0 = time.perf_counter()
        for n in names:
            traj = runner(seed_inputs[n], snapshot)
            sc = score_trajectory(traj, golds[n])
            for m in METRICS:
                scores[m].append(sc[m]["score"])
            for v in traj["verdicts"]:
                verdicts[v["alert_id"]] = v["affected"]
        latency_by_arm[arm] = time.perf_counter() - t0
        scores_by_arm[arm] = scores
        verdicts_by_arm[arm] = verdicts

    for n in names:
        for a in seed_inputs[n]["alerts"]:
            if a["alert_id"] not in alert_ids:
                alert_ids.append(a["alert_id"])

    aggregates = {arm: {m: _mean(scores_by_arm[arm][m]) for m in METRICS} for arm in arms}

    pairwise = {}
    for a, b in itertools.combinations(arms, 2):
        pairwise[f"{a}__vs__{b}"] = {
            m: compare_arms(scores_by_arm[a][m], scores_by_arm[b][m],
                            n_boot=N_BOOT, seed=BOOT_SEED)
            for m in METRICS
        }

    flip_matrix = _flip_matrix(arms, verdicts_by_arm, alert_ids)
    both = {"single_agent", "multi_agent"} <= set(arms)
    flip_count = flip_matrix["multi_agent"]["single_agent"] if both else None

    return {
        "corpus_snapshot_id": snapshot.snapshot_id,
        "n_trajectories": len(names),
        "n_alerts": len(alert_ids),
        "arms_run": list(arms),
        "arms_pending": [a for a in LLM_ARMS if a not in arms],
        "metrics": list(METRICS),
        "aggregates": aggregates,
        "pairwise_ci": pairwise,
        "verdict_flip_matrix": flip_matrix,
        "flip_count_multi_vs_single": flip_count,
        "_latency_seconds": {arm: latency_by_arm[arm] for arm in arms},  # report-only
    }


def _fmt_ci(ci: dict) -> str:
    if ci["observed"] is None:
        return "n/a"
    star = " *" if ci["significant"] else ""
    return f"{ci['observed']:+.4f} [{ci['ci_lo']:+.4f}, {ci['ci_hi']:+.4f}]{star}"


def format_markdown(result: dict) -> str:
    """Human report — numbers ONLY from `result` (every figure traceable to the JSON)."""
    arms = result["arms_run"]
    pending = result["arms_pending"]
    lines = [
        "# DepGuard v0.1 — three-arm ablation",
        "",
        f"- corpus_snapshot_id: `{result['corpus_snapshot_id']}`",
        f"- golden trajectories: {result['n_trajectories']}  ·  alerts: {result['n_alerts']}",
        f"- arms run: {', '.join(arms)}",
    ]
    if pending:
        lines.append(
            f"- **arms pending (require `LLM_API_KEY`): {', '.join(pending)}** — "
            "re-run `python scripts/run_ablation.py` with a DeepSeek key to fill these in.")
    lines += ["", "## Per-arm metrics (mean over the golden set)", ""]
    header = "| arm | " + " | ".join(result["metrics"]) + " | latency (s) |"
    lines.append(header)
    lines.append("|" + "---|" * (len(result["metrics"]) + 2))
    for arm in arms:
        agg = result["aggregates"][arm]
        row = [arm] + [f"{agg[m]:.4f}" for m in result["metrics"]]
        row.append(f"{result['_latency_seconds'][arm]:.2f}")
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## Pairwise paired-bootstrap 95% CI on Δ (arm_A − arm_B)",
              f"_{N_BOOT:,} resamples, seed {BOOT_SEED}; `*` = interval excludes 0._", ""]
    if result["pairwise_ci"]:
        lines.append("| pair | " + " | ".join(result["metrics"]) + " |")
        lines.append("|" + "---|" * (len(result["metrics"]) + 1))
        for pair, cis in result["pairwise_ci"].items():
            row = [pair.replace("__vs__", " − ")]
            row += [_fmt_ci(cis[m]) for m in result["metrics"]]
            lines.append("| " + " | ".join(row) + " |")
    else:
        lines.append("_pending — only one arm ran; no pairwise comparison possible yet._")

    lines += ["", "## Verdict-flip matrix (alerts whose actionable `affected` differs)", ""]
    lines.append("| A ⧵ B | " + " | ".join(arms) + " |")
    lines.append("|" + "---|" * (len(arms) + 1))
    for a in arms:
        row = [a] + [str(result["verdict_flip_matrix"][a][b]) for b in arms]
        lines.append("| " + " | ".join(row) + " |")
    fc = result["flip_count_multi_vs_single"]
    lines += ["", f"**Flip count (multi_agent vs single_agent): "
              f"{'pending — LLM arms not run' if fc is None else fc}**", ""]
    return "\n".join(lines) + "\n"
