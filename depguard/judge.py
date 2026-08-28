"""Calibrated LLM judge for reconciliation-note clarity (DECISIONS.md §4.3, v1.3.0).

WHAT THIS MAY AND MAY NOT SCORE.

§4.3 permits an LLM judge for **soft narrative quality only** and forbids it anywhere near
verdict correctness, which is mechanical (§5). That line is load-bearing: the entire claim
of this repo is that no result depends on an LLM grading an LLM. So the judge scores exactly
one thing — how clearly a `reconciliation_note` explains a source disagreement to the
engineer who has to act on it — and `tests/test_judge_calibration.py` asserts by import
graph that nothing in the correctness path can reach this module.

A note's clarity has no mechanical ground truth, which is precisely why it is the only place
a judge is allowed. Containment does have one, so a judge there would be strictly worse than
the oracle already in place.

CALIBRATION IS A GATE, NOT A FORMALITY. `USE_JUDGE_THRESHOLD` is checked against measured
agreement with the hand-labelled audit set. If the judge does not clear it, the honest
outcome is to report the disagreement and NOT use the judge — a miscalibrated judge that
ships is worse than no judge, because its numbers look like measurements.

THE RUBRIC IS PUBLISHED (below, and mirrored in `golden/judge_rubric.md`) so a reader can
check the judge against it rather than taking a score on trust.
"""

from __future__ import annotations

import json
import os
import re

__all__ = ["RUBRIC", "LEVELS", "judge_note", "USE_JUDGE_THRESHOLD",
           "MAX_TRAP_DELTA", "agreement_stats", "judge_is_usable"]

#: Minimum quadratic-weighted kappa against the human audit set. 0.60 is the conventional
#: "moderate-to-substantial" boundary; chosen in advance, not fitted to the result.
USE_JUDGE_THRESHOLD = 0.60

#: Kappa alone is NOT sufficient, and the first calibration run proved it. The judge scored
#: kappa 0.8366 — comfortably over the threshold — while giving the `confident_but_wrong`
#: trap 5 out of 5. That note is fluent, well-structured and factually false: it denies a
#: disagreement that exists. The judge's own stated reason was "the note clearly states both
#: sources agree ... no action is needed."
#:
#: It cannot do better, and that is the finding. §4.3 forbids giving a clarity judge the
#: ground truth, so it has no way to separate "clearly explains the situation" from "clearly
#: explains a FABRICATED situation" — fluent falsehood reads as clarity. An aggregate score
#: averages that failure away, which is exactly why the traps are gated SEPARATELY: a judge
#: that blows one is not usable as a standalone quality signal, whatever its kappa.
MAX_TRAP_DELTA = 1

LEVELS = {
    1: "useless — says a conflict exists but nothing an engineer could act on",
    2: "vague — names one side or one fact, no version and no direction",
    3: "adequate — states what each source claims, but the reader must infer the action",
    4: "clear — names the version, both sources' claims, and which one governs",
    5: "excellent — all of level 4, plus the concrete consequence for the pinned version",
}

RUBRIC = """Score a dependency-triage RECONCILIATION NOTE from 1 to 5.

A reconciliation note is written when two advisory sources disagree about whether a specific
published version is affected. Its only job is to let an on-call engineer decide what to do
without re-reading both sources.

Score ONLY the clarity and actionability of the writing. Do NOT judge whether the underlying
security verdict is correct — that is decided mechanically elsewhere and is not your call.

1 — useless: asserts a conflict exists but gives nothing actionable.
2 — vague: names one source or one fact; no version number and no direction.
3 — adequate: states what each source claims, but leaves the reader to infer what to do.
4 — clear: names the specific version, both sources' claims, and which one governs.
5 — excellent: everything in 4, plus the concrete consequence for the pinned version.

Reply with ONE JSON object and nothing else: {"score": <1-5>, "reason": "<one sentence>"}
"""


def judge_note(note: str, *, context: str = "") -> dict:
    """Score one reconciliation note against RUBRIC. Requires LLM_API_KEY.

    Returns {"score": int|None, "reason": str}. `score=None` means the judge failed to
    produce a usable reply — surfaced, never silently coerced to a number, because a
    fabricated score is indistinguishable from a measured one once it is in a table.
    """
    from langchain_openai import ChatOpenAI

    from depguard.llm_meter import METER

    client = ChatOpenAI(
        model=os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        api_key=os.environ["LLM_API_KEY"],
        temperature=0,
        timeout=120,
        max_retries=1,
    )
    prompt = f"{RUBRIC}\n\nCONTEXT: {context or '(none)'}\n\nNOTE TO SCORE:\n{note!r}\n"
    for _ in range(2):
        try:
            resp = client.invoke(prompt)
        except Exception:
            continue
        METER.record_call(resp)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            continue
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        score = parsed.get("score")
        if isinstance(score, (int, float)) and 1 <= score <= 5:
            return {"score": int(score), "reason": str(parsed.get("reason", ""))[:300]}
    return {"score": None, "reason": "judge produced no usable score"}


def agreement_stats(human: list[int], judge: list[int]) -> dict:
    """Agreement between the judge and the human audit labels.

    Reports three numbers because one would mislead. Exact agreement is harsh on an ordinal
    scale where adjacent levels genuinely blur; within-1 is generous and would flatter almost
    any judge; quadratic-weighted kappa corrects for agreement expected by chance and
    penalises far misses more than near ones, so it is the one the threshold is set on.
    """
    pairs = [(h, j) for h, j in zip(human, judge) if j is not None]
    n = len(pairs)
    if n == 0:
        return {"n": 0, "exact": 0.0, "within_1": 0.0, "kappa_quadratic": 0.0,
                "unscored": len(human)}
    exact = sum(1 for h, j in pairs if h == j) / n
    within = sum(1 for h, j in pairs if abs(h - j) <= 1) / n

    # Quadratic-weighted kappa over the 1..5 grid.
    k = 5
    obs = [[0] * k for _ in range(k)]
    for h, j in pairs:
        obs[h - 1][j - 1] += 1
    hrow = [sum(1 for h, _ in pairs if h == i + 1) for i in range(k)]
    jcol = [sum(1 for _, j in pairs if j == i + 1) for i in range(k)]
    num = den = 0.0
    for a in range(k):
        for b in range(k):
            w = ((a - b) ** 2) / ((k - 1) ** 2)
            num += w * obs[a][b]
            den += w * (hrow[a] * jcol[b] / n)
    kappa = 1.0 - (num / den) if den else 1.0
    return {"n": n, "exact": exact, "within_1": within,
            "kappa_quadratic": kappa, "unscored": len(human) - n}


def judge_is_usable(stats: dict, trap_deltas: dict[str, int | None]) -> tuple[bool, list[str]]:
    """Two gates, both of which must pass. Returns (usable, reasons_it_failed).

    Aggregate agreement is necessary and not sufficient: the first run cleared kappa 0.60
    by a wide margin while scoring a fluent falsehood 5/5. Averaging that into a single
    number is how a judge with a known, reproducible failure mode gets shipped as a
    measurement, so each trap is checked on its own.
    """
    failures = []
    if stats.get("kappa_quadratic", 0.0) < USE_JUDGE_THRESHOLD:
        failures.append(
            f"kappa {stats.get('kappa_quadratic', 0.0):.4f} < {USE_JUDGE_THRESHOLD}")
    for name, delta in sorted(trap_deltas.items()):
        if delta is None:
            failures.append(f"trap {name}: judge produced no score")
        elif abs(delta) > MAX_TRAP_DELTA:
            failures.append(f"trap {name}: off by {delta:+d} (max {MAX_TRAP_DELTA})")
    return (not failures), failures
