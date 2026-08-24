# DepGuard

[![CI](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/ci.yml)
[![eval-gate](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/eval-gate.yml/badge.svg?branch=main)](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/eval-gate.yml)

Most dependency-vulnerability alerts are false alarms. A scanner flags a pinned version as
vulnerable, an engineer spends an afternoon proving it isn't, and the cycle repeats.
DepGuard reads each alert, decides whether the pinned version is actually inside the
advisory's affected range, shows the evidence it used, and names the smallest safe upgrade.

The interesting part isn't the agent. It's that this task has a **mechanical ground truth**,
so I can measure exactly where an LLM earns its cost and where it doesn't — with a
confidence interval instead of a vibe.

## The result: a frontier, not a win

Two slices of the same frozen corpus, scored by the same mechanical verifier. No LLM judge
anywhere in the correctness path.

### Slice 1 — machine-readable ranges. Everything ties, and that's the point.

The advisory's affected range is structured data, so a plain semver script decides it
exactly. Nothing can beat a correct script here — this slice is the **control**.

| arm | correctness | groundedness | latency | cost |
|---|---|---|---|---|
| `deterministic_script` | 1.0000 | 1.0000 | 0.5 s | $0.00 |
| `single_agent` (ReAct) | 0.5517 | 0.6207 | 1002 s | $0.114 |
| `multi_agent` (planner→executor) | 1.0000 | 1.0000 | 147 s | $0.019 |

`deterministic_script − multi_agent` = **+0.0000 on every metric — an identity, not a
measurement.** See [why](#why-slice-1-ties) below; the old release reported it as a
`[0, 0]` confidence interval, which flattered it.

### Slice 2 — the ranges are redacted. Only the prose survives.

Same corpus, one pure transform: strip `ranges` and `versions`, keep the advisory text. The
affected range now exists only in English. `record_containment` **raises** on a redacted
record, so the script's failure is an exception, not a contested number.

| arm | range accuracy | correct | wrong abstain | wrong range |
|---|---|---|---|---|
| `deterministic_script` | **0.1500** | 6 / 40 | 34 | 0 |
| `regex_baseline` | **0.4750** | 19 / 40 | 11 | 10 |
| `llm_extractor` | **0.6417** [0.6250–0.6500] | 25.7 / 40 | 1.7 | 12.7 |

| Δ | range accuracy, 95% CI |
|---|---|
| `llm_extractor − deterministic_script` | **+0.4917 [+0.3417, +0.6500]** * |
| `llm_extractor − regex_baseline` | **+0.1667 [+0.0665, +0.2833]** * |
| `regex_baseline − deterministic_script` | +0.3250 [+0.1750, +0.4750] * |

Accuracy and counts are means over 3 runs (hence the fractions); latency, calls and cost are
totals over every run paid for; the bootstrap uses each seed's pass rate across runs, so the
CI matches the mean beside it. 120 LLM calls, **0 extractor fallbacks**, $0.25 all in.

The script's 6 correct answers are **only** the 6 seeds whose prose names no version at all,
where abstaining is right. On the 34 records that do describe a range it scores **0/34**.
The ordering is strict and holds in **every one of the 3 runs**: the LLM wins 6–7 seeds the
regex loses and loses **none** it wins; the regex beats the script on 13 and loses none.

An earlier version of this table read `regex 0.4000` and `llm − regex +0.2500`. That delta
was inflated by two bugs in my own baseline — `"2.1.0 through 2.5.3"` was parsed as
*excluding* 2.5.3, and the grammar could not read a `v`-prefixed version at all. Fixing the
control cost the headline a third of its size. The corrected number is above.

So: **a script is free, instant and unbeatable when the data is structured. The moment the
same fact is only in prose, it drops to zero and the model is worth paying for.** That's the
boundary, measured on one corpus with one verifier.

## What each arm actually gets wrong

The failure modes are more useful than the scores, and no aggregate shows them.

**The LLM over-scopes, in the safe direction.** Its dominant error is dropping the
advisory's lower bound and claiming everything before the fix is vulnerable — **9 of its 12
range errors propose `introduced: "0"`** where the advisory scoped the flaw to a branch
(`cryptography` 40.0.0, `redis` 4.2.0, `lodash` 4.0.0, `prismjs` 1.14.0…). Counting by
direction, **10 of 12 over-claim which versions are affected and only 2 under-claim** — it
produces false positives, which is the thing DepGuard exists to reduce, rather than missing
live vulnerabilities. Three residual misses are pure boundary slips (`cross-spawn` 6.0.6,
`hosted-git-info` 2.8.9), the exact inclusive/exclusive semantics the script gets right for
free.

**The regex baseline fails by giving up.** 11 of its 21 misses are abstentions — prose forms
its grammar doesn't cover. It is a good-faith baseline, not a straw man: it handles the
interleaved branch form ("Django 2.2 before 2.2.28, 3.2 before 3.2.13, and 4.0 before
4.0.4") correctly, and two rounds of bug-fixing went into it *after* it was first measured.

**The single agent skips evidence, not judgment.** On slice 1, on the 28 of 29 alerts where
it answered, its affected/not-affected call was **correct every time**. It lost points by
**skipping `crosscheck_second_source` on 22 of 29 runs**. Correctness and groundedness
diverge in both directions — 5 trajectories right but ungrounded, 7 the inverse.

Across both slices the same shape: the LLM's mistakes are in the *safe* direction and cost
precision, not safety. Scaffolding buys evidence discipline; it does not buy judgment.

## Why slice 1 ties

Because it could not have done anything else, for two independent reasons:

- **The script *is* the label function.** `compute_minimal_fix` delegates to
  `minimal_fix_gold`, the same function that labels gold. On a decidable task the
  deterministic arm cannot score anything but 1.0000.
- **The planner prompt dictated the plan.** `graph.py` enumerates the canonical 8-step plan
  verbatim and `_parse` rejects anything off-enum, so the LLM had no freedom over anything
  scored.

Measured: the two arms' trajectories are **byte-identical** across verdicts, evidence,
`final_answer`, tool sequence, tool arguments *and* tool results — 174 tool calls each. The
only differing content is 232 free-text `rationale` strings that no metric reads. $0.019 and
147 seconds bought 232 sentences.

A zero-variance delta now prints as `(identity: identical on all 29)` rather than `[0, 0]`,
so it can't be read as precision again.

## Two gates, because one has a blind spot

**The eval gate** re-scores the deterministic arm on every push and blocks the merge if
correctness or groundedness slips. Delete one planner step and it goes red with a
gold-vs-actual diff.

**It cannot catch oracle bugs, and here's the proof.** It recomputes gold with the same
functions the tools call, so prediction and label move together. Invert one line in
`oracle.py` — make a `fixed` event close inclusive, i.e. "the patched release is still
vulnerable" — and **13 of 29 golden verdicts flip**, including the lodash 4.17.21 case this
README leads with, while **`correctness` stays at 1.0000**. The gate goes red only via one
incidental groundedness row on a seed that isn't among the 13. It caught that by luck.

So `golden/oracle_truth.jsonl` runs as a **separate CI step**: 87 rows derived by hand from
the OSV spec, never by running the oracle, weighted toward boundaries. Under that injected
bug, 16 of 87 fail.

    eval gate           → orchestration regressions
    oracle truth table  → oracle bugs

## Reproduce

```bash
pip install -e .

# keyless — the deterministic and regex arms need no API key
python scripts/run_eval.py check
python -m pytest tests/test_oracle_truth.py -q
python scripts/run_prose_slice.py --no-llm

# the LLM arms need a DeepSeek key; --repeats reports a spread, not one observation
python scripts/run_ablation.py --repeats 3
python scripts/run_prose_slice.py --repeats 3 --workers 8
```

Every number above is in [`results/`](results/): aggregates and CIs in the JSON, raw
trajectories in [`results/trajectories/`](results/trajectories/), per-seed prose rows in
`results/prose_slice_rows.json`.

Read [LIMITATIONS.md](LIMITATIONS.md) before trusting any of it — it leads with the two
things that most change how the tables above should be read.

## Quickstart

```bash
# CLI: triage a manifest against the frozen corpus (no key, no network)
depguard-triage examples/package.json

# Web demo: paste a package.json, watch verdicts stream in
pip install -e ".[demo]" && uvicorn depguard.webapp:app --port 8080

# MCP: the six tools, in any stock client
claude mcp add depguard -- depguard-mcp
```

Claude Desktop config in [docs/MCP.md](docs/MCP.md); Cloud Run and Langfuse capture in
[docs/DEPLOY.md](docs/DEPLOY.md).

## How it works

```
manifest + scanner alerts
        │
   planner ── retriever ── tool_worker ── verifier ──► one Verdict per alert
  (rule or LLM)   │            │             │          affected? · minimal fix · evidence
                  └──── six typed {ok,data,error} tools ────┘
```

For each alert DepGuard answers three things: is the pinned version actually in the
advisory's affected range, what's the authoritative advisory plus the exact range-event
evidence, and what's the smallest published version that clears it — grounded in the
deps.dev version list, never invented.

Ground truth is a committed OSV + deps.dev snapshot
(`corpus_snapshot_id = depguard-corpus-2026-07-01-c6f3471a2245`) stamped on every evidence
row; the verifier refuses to score across a snapshot mismatch, and nothing in the tool layer
touches the network. The prose slice is a pure transform of those same frozen bytes, so the
snapshot id is unchanged and slice 1 stays exactly reproducible.

One caveat worth stating plainly: the 71–90% scanner false-positive figures usually quoted
are mostly about call-graph reachability, which DepGuard doesn't attempt. This handles the
version-range-containment slice — the part with a mechanical ground truth. The design is
frozen in [DECISIONS.md](DECISIONS.md); P5 is §5.1.

## License and data

Code is MIT. OSV records are CC0-1.0 or CC-BY-4.0 (GHSA-origin records keep their
attribution); deps.dev-derived rows are CC-BY-4.0 with per-row provenance. The corpus is a
frozen snapshot, so verdicts reflect the snapshot date rather than live advisory data. See
`NOTICE/ATTRIBUTION.md` and DECISIONS.md §1.7.
