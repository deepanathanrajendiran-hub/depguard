# Reconciliation-note judge rubric

Published so a reader can check the judge against it rather than trusting a score.
Applied by `depguard/judge.py`; calibrated against `golden/judge_audit.jsonl`.

**Scope (DECISIONS.md §4.3):** this judge scores SOFT NARRATIVE QUALITY ONLY. It never
scores verdict correctness, which is mechanical (§5). A test asserts by import graph that
nothing in the correctness path can reach it.

**Usability gate:** the judge is only used if quadratic-weighted kappa against the human
audit set is >= 0.6. Below that the honest outcome is to report the
disagreement and not use the judge — a miscalibrated judge that ships is worse than none,
because its numbers look like measurements.

## The rubric, verbatim as sent to the model

```
Score a dependency-triage RECONCILIATION NOTE from 1 to 5.

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
```

## Levels

- **1** — useless — says a conflict exists but nothing an engineer could act on
- **2** — vague — names one side or one fact, no version and no direction
- **3** — adequate — states what each source claims, but the reader must infer the action
- **4** — clear — names the version, both sources' claims, and which one governs
- **5** — excellent — all of level 4, plus the concrete consequence for the pinned version
