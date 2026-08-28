# DepGuard

[![CI](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/ci.yml)
[![eval-gate](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/eval-gate.yml/badge.svg?branch=main)](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/eval-gate.yml)

Most dependency-vulnerability alerts are false alarms. A scanner flags a pinned version as
vulnerable, an engineer spends an afternoon proving it isn't, and the cycle repeats.
DepGuard reads each alert, decides whether the pinned version is actually inside the
advisory's affected range, shows the evidence it used, and names the smallest safe upgrade.

This task has a **mechanical ground truth**, which is rare and valuable: it means the agent
can be *verified*, not just demoed. The deliverable is the eval harness that does the
verifying.

## The result: the agent is verified correct, and it reaches further

Two slices of the same frozen corpus, one mechanical verifier, no LLM judge anywhere in the
correctness path.

### Slice 1 — the agentic system agrees with a known-correct reference, exactly

Where the advisory's affected range is structured data, a plain semver pipeline decides it
exactly and serves as a **reference implementation**. Running the agentic system against it
is differential testing: two independent implementations, one oracle, and any disagreement
is a defect in one of them.

**There were no disagreements.** `multi_agent` reproduces the reference on all **38
trajectories across npm, PyPI, crates.io and Go** — every verdict, every minimal-fix, every
evidence row, every tool call — with **0 planner fallbacks**, so the agreement is genuine LLM
planning and not a silent fall-through to the rule-based path (instrumented precisely because
that artifact would look identical). That is a validation result: on the slice where
correctness is checkable, the agentic system is *checkably correct* — including on Go
pseudo-versions and `+incompatible` build metadata.

| arm | correctness | groundedness | latency | cost |
|---|---|---|---|---|
| `deterministic_script` | 1.0000 | 1.0000 | 1.0 s | $0.00 |
| `single_agent` (ReAct) | 0.6842 [0.6053–0.7368] | 0.7895 [0.7105–0.8421] | 963 s | $0.124 |
| `multi_agent` (planner→executor) | 1.0000 [1.0000–1.0000] | 1.0000 | 154 s | $0.021 |

LLM rows are the mean of 3 runs with the min–max spread; the deterministic arm is
bit-reproducible. `deterministic_script − multi_agent` = `+0.0000` on every metric, printed
as **`(identity: identical on all 29)`** rather than as a confidence interval — because a
zero-variance delta is exact agreement, and dressing it up as a `[0, 0]` CI would imply a
precision estimate that isn't there.

The comparison also has teeth in the other direction: `single_agent`, the same LLM without
the planner→executor scaffold, does **not** reach the reference (0.6842 [0.6053–0.7368]). So
the agreement above is a property of this architecture, not something any LLM arm gets for
free.

**One caveat, stated up front:** v0.1 shipped `single_agent correctness = 0.5517` from a
single run. It has not reproduced since, in either of two later three-run measurements. That
is ordinary run-to-run variance, which is exactly what an n=1 measurement cannot see — every
LLM figure here is a mean over repeats for that reason.

### Slice 2 — where the reference implementation cannot follow

Agreement on slice 1 shows the agent is correct. It does not yet show it is *useful*, since
a script gets the same answers for free. So the same corpus is re-run through one pure
transform: strip `ranges` and `versions`, keep the advisory text. The affected range now
exists only in English, and `record_containment` **raises** on a redacted record — the
deterministic path doesn't score badly here, it structurally cannot answer at all.

| arm | range accuracy | correct | wrong abstain | wrong range |
|---|---|---|---|---|
| `deterministic_script` | **0.1837** | 9 / 49 | 40 | 0 |
| `regex_baseline` | **0.4490** | 22 / 49 | 15 | 12 |
| `llm_extractor` | **0.6259** [0.6122–0.6327] | 30.7 / 49 | 1.7 | 16.7 |

| Δ | range accuracy, 95% CI |
|---|---|
| `llm_extractor − deterministic_script` | **+0.4422 [+0.3061, +0.5782]** * |
| `llm_extractor − regex_baseline` | **+0.1769 [+0.0816, +0.2859]** * |
| `regex_baseline − deterministic_script` | +0.2653 [+0.1429, +0.3878] * |

Accuracy and counts are means over 3 runs (hence the fractions); latency, calls and cost are
totals over every run paid for; the bootstrap uses each seed's pass rate across runs, so the
CI matches the mean beside it. 147 LLM calls, **0 extractor fallbacks**, $0.30 all in.

The script's 9 correct answers are **only** the 9 seeds whose prose names no version at all,
where abstaining is right. On the 40 records that do describe a range it scores **0/40**.
The ordering is strict and holds in **every one of the 3 runs**: the LLM wins 8 seeds the
regex loses and loses **none** it wins; the regex beats the script on 13 and loses none.

An earlier version of this table read `regex 0.4000` and `llm − regex +0.2500`, on a smaller
corpus. That delta was inflated by two bugs in my own baseline — `"2.1.0 through 2.5.3"` was parsed as
*excluding* 2.5.3, and the grammar could not read a `v`-prefixed version at all. Fixing the
control cost the headline a third of its size. The corrected number is above.

Read together, the two slices say something a single number can't: **the agentic system is
verifiably correct wherever correctness is checkable, and it keeps working past the point
where the checkable path stops.** That is the case for shipping it — not "the LLM beat a
script", but "the LLM matches a proven reference *and* covers the inputs the reference
can't.

## Where the system's errors actually go

Knowing an arm's score is less useful than knowing which direction it fails in. None of this
is visible in an aggregate; it comes out of the per-trajectory rows.

**The LLM over-scopes, in the safe direction.** Its dominant error is dropping the
advisory's lower bound and claiming everything before the fix is vulnerable — **most of its
range errors propose `introduced: "0"`** where the advisory scoped the flaw to a branch
(`cryptography` 40.0.0, `redis` 4.2.0, `lodash` 4.0.0, `prismjs` 1.14.0…). Counting by
direction, the large majority **over-claim** which versions are affected rather than
under-claiming — it produces false positives, which is the thing DepGuard exists to reduce,
rather than missing live vulnerabilities. A handful of residual misses are pure boundary
slips (`cross-spawn` 6.0.6, `hosted-git-info` 2.8.9), the exact inclusive/exclusive semantics
the script gets right for free.

**The regex baseline fails by giving up.** 15 of its 27 misses are abstentions — prose forms
its grammar doesn't cover. It is a good-faith baseline, not a straw man: it handles the
interleaved branch form ("Django 2.2 before 2.2.28, 3.2 before 3.2.13, and 4.0 before
4.0.4") correctly, and two rounds of bug-fixing went into it *after* it was first measured.

**The single agent skips evidence, not judgment.** This is the slice-1 finding that keeps
reproducing: across every measured run its affected/not-affected call has been correct on
**every alert it answered**, and so has `withdrawn`. It loses points only on evidence it
skipped — `crosscheck_second_source` goes unrun on a large fraction of alerts, taking
`source_agreement` down with it.

Note the split: the *direction* of that finding is stable across runs, the *magnitude* is
not. Anything quoted as a rate here should be read as one of a handful of samples.

Across both slices the same shape: the LLM's mistakes are in the *safe* direction and cost
precision, not safety. Scaffolding buys evidence discipline; it does not buy judgment.

## How strong is the slice-1 agreement, exactly?

Strong enough to be worth stating precisely, and bounded enough to be worth qualifying.

**What it is.** The two arms' trajectories are **byte-identical** across verdicts, evidence,
`final_answer`, tool sequence, tool arguments *and* tool results — 174 tool calls each. Not
"the same score": the same execution. For a system whose job is to be right about security,
reproducing a verified reference exactly, on every alert, is the result you want.

**What it is not.** Two things bound how far it generalises, and both are design choices
made to get a mechanical oracle at all:

- The reference shares its containment and minimal-fix functions with the tools
  (`compute_minimal_fix` → `minimal_fix_gold`), which is what stops the eval drifting away
  from the system — but it also means the reference is correct *by construction* on this
  slice. Oracle bugs are therefore watched by a separate hand-written truth table, below.
- The planner prompt names the canonical step sequence, so slice 1 measures whether the
  agent executes a known-good plan faithfully, not whether it invents one. That is the right
  thing to verify for a security tool, and it is not the same as open-ended planning. Slice 2
  is where the model has to produce something the prompt cannot contain.

So: slice 1 certifies conformance, slice 2 measures capability. Reported separately on
purpose.

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
