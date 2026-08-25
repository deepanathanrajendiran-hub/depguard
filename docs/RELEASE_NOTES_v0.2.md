# DepGuard v0.2 — the agent, verified

v0.1 reported that the agentic system and a deterministic reference implementation produce
identical results, and left it there. v0.2 says what that actually establishes, adds the
slice that shows where the agent goes beyond the reference, and fixes six defects found
along the way.

## What the agreement establishes

`multi_agent` reproduces the deterministic reference on all 29 golden trajectories —
**byte-identical** across verdicts, evidence, `final_answer`, tool sequence, tool arguments
and tool results, 174 tool calls each — with **0 planner fallbacks**, so the agreement is
genuine LLM planning rather than a silent fall-through to the rule-based path. (That
instrumentation exists because a fallback would produce numerically identical output; it is
the difference between a verified result and a coincidence.)

Two independent implementations, one mechanical oracle, zero disagreements. That is
differential testing, and it is the strongest correctness statement available for a security
tool: on every input where the right answer is checkable, the agent is checkably right.

It is also a property of *this* architecture rather than of LLMs generally — `single_agent`,
the same model without the planner→executor scaffold, does not reach the reference
(0.7471 [0.6552–0.7931]).

**How far it generalises, stated plainly.** The reference shares its containment and
minimal-fix functions with the tools, which is what keeps the eval from drifting away from
the system — and also means the reference is correct by construction on this slice, so
oracle bugs need a separate watchdog (added below). And the planner prompt names the
canonical step sequence, so this slice verifies faithful execution of a known-good plan, not
open-ended planning. Slice 1 certifies conformance; slice 2 measures capability.

## Slice 2: where the reference implementation cannot follow

`depguard/redact.py` strips `ranges` and `versions` from the frozen records — a pure
function of already-frozen bytes, so `corpus_snapshot_id` is unchanged and every v0.1
figure stays reproducible. The affected range then survives only in the advisory prose. Every
`affected[]` entry abstains and `record_containment` **raises**: the script's failure is an
exception asserted by a committed test, not a contested number.

**P5 SEMANTIC-RANGE-EQUIVALENCE** (DECISIONS.md §5.1) scores reconstructions mechanically.
The claim is materialised against the frozen published-version list and compared to the
unredacted record by containment bitvector, running the **same `record_containment` on both
sides** — so `last_affected: 4.17.20` and `fixed: 4.17.21` score equal exactly when no
release separates them, while an off-by-one fails and names the version. The shared-oracle
principle holds more literally here than anywhere else in the system, and no LLM judge
touches the correctness path.

| arm | range accuracy | correct | wrong abstain | wrong range |
|---|---|---|---|---|
| `deterministic_script` | **0.1500** | 6 / 40 | 34 | 0 |
| `regex_baseline` | **0.4750** | 19 / 40 | 11 | 10 |
| `llm_extractor` | **0.6417** [0.6250–0.6500] | 25.7 / 40 | 1.7 | 12.7 |

`llm − script` **+0.4917 [+0.3417, +0.6500]** · `llm − regex` **+0.1667 [+0.0665, +0.2833]**
· `regex − script` +0.3250 [+0.1750, +0.4750]. All significant. 3 repeats, 120 LLM calls,
**0 extractor fallbacks**, $0.25 all in. Accuracy and counts are means over runs; latency,
calls and cost are totals; the bootstrap uses each seed's pass rate across runs.

The ordering is strict and holds in **every one of the 3 runs** — the LLM wins 6–7 seeds the
regex loses and loses **none** it wins (verified per-run from `per_seed` in
`results/prose_slice_partial.json`); the regex beats the script on 13 and loses none. The
script's 6 correct answers are only the seeds whose prose names no version at all; on the 34
records that describe a range it scores **0/34**.

**These numbers replace an earlier set.** The first measurement read `regex 0.4000` and
`llm − regex +0.2500`, both inflated by two defects in my own baseline (see below). Fixing
the control cost the headline delta a third of its size.

**The headline across both slices:** the agentic system matches a proven reference wherever
the answer is checkable, and keeps working on the inputs the reference structurally cannot
handle. The `regex_baseline` is there so that "you should have just written the parser" is
answered with a measured number rather than an opinion.

## Failure modes, which are the useful part

- **The LLM over-scopes, in the safe direction.** Its dominant error is dropping the
  advisory's lower bound: **9 of 12 range errors propose `introduced: "0"`**, claiming
  everything before the fix, where the advisory scoped the flaw to a branch (`cryptography`
  40.0.0, `redis` 4.2.0, `lodash` 4.0.0, `prismjs` 1.14.0). By direction, **10 of 12
  over-claim** which versions are affected and 2 under-claim — it manufactures false
  positives, the thing DepGuard exists to reduce, rather than missing live vulnerabilities.
- **The regex fails by giving up.** 13 of its 24 misses are abstentions. It is not a straw
  man: it handles the interleaved branch form correctly.
- **The single agent skips evidence, not judgment.** On the 28 of 29 alerts it answered, its
  affected/not-affected call was correct every time; it skipped `crosscheck_second_source`
  on **22 of 29 runs**.

## Defects found and fixed

1. **Fail-unsafe verdict counting.** `trajectory.py::build()` computed
   `n_false_positive = n_alerts - n_true_positive`, so an unanswered alert silently became a
   dismissed false positive. The shipped v0.1 `single_agent` run on `tp_axios` abandoned with
   **0 tool calls and 0 verdicts** yet reported `n_false_positive: 1` against a gold of
   `affected=True` — **a real CVE reported as dismissed by a run that did no work.** Summary
   now derives from emitted verdicts only, with a new `n_unresolved`.
2. **Error envelopes read as "not affected".** `Pipeline._exec_check` resolved any tool error
   to `contained=False`. Most visibly, an unpinned `^4.17.0` was reported **NOT AFFECTED**
   when all DepGuard had established was that it could not parse the version.
3. **`action_advancement` was inverted.** On a one-alert corpus it reduced to
   `1 / n_executed_steps`, scoring an arm higher for doing less; within-arm correlation with
   correctness **−0.172**, and the v0.1 report consequently marked the *deterministic* arm
   "significantly worse" on it than an arm answering 13 of 29 alerts wrong. Replaced by
   `verdict_yield`.
4. **The "4-predicate verifier" claim was not true.** `score_trajectory` called a
   field-equality lookalike and never called `verifier.py::verify_verdict`, so neither P4's
   non-empty-`reconciliation_note` rule nor the exclusion path was enforced on any published
   number. Now routed through the real verifier — **no published figure moved**.
5. **The extractor scored correct answers as wrong.** The model emits
   `{"introduced": "0", "fixed": "4.3.6"}`; the parser required one key per event and dropped
   them, turning correct reconstructions into empty proposals. Fixed before any number was
   reported.
6. **The control was crippled by its own grammar, and it inflated the headline.** The regex
   baseline put `"through"` in the same alternation as `"before"`, so `"requests 2.1.0
   through 2.5.3"` was parsed as *excluding* 2.5.3 — both corpus seeds using that form failed
   on exactly the boundary version. Separately its version pattern could not match a
   `v`-prefixed release, so `"fixed in v1.27.0"` read as "no version mentioned" on 3 more
   seeds, while `redact._VERSION_TOKEN` fires inside `v1.27.0` anyway — gold called those
   seeds decidable and the control was scored against a token it could not see.
   `regex_baseline` went **0.4000 → 0.4750** and the headline `llm − regex` delta fell from
   +0.2500 to **+0.1667**. A baseline weakened by its own bugs flatters the arm it is
   compared against, and it flattered mine.
7. **The published LLM row mixed a 3-run mean with run-1 counts.** `dict(runs[0], ...)`
   copied run 1's counts, latency, calls and cost and overlaid a mean accuracy, so the table
   read `0.6417 … 26 | 40` when 26/40 = 0.65, and reported a third of the real spend — while
   the CIs came from run 1's per-seed vector, making a delta printed beside the mean actually
   a delta against run 1.
8. **The fail-unsafe fix covered only one of two arms.** `arms/single_agent.py` still turned
   an error envelope into `affected: false` and fed that fabricated `False` back to its own
   ReAct policy, so the class of bug these notes claimed to have removed was still shipping
   in one of the three ablation arms.

Findings 6–8 came from an independent review of the branch, after the first set of numbers
had already been written into this file. They are listed here rather than quietly corrected
because "the harness catches what I would otherwise ship" is the entire claim of the project,
and it only means anything if it applies to my own work.

## The eval gate's blind spot, and the fix

The gate recomputes gold with the same functions the tools call, so prediction and label move
together. Inverting one line in `oracle.py` — a `fixed` event closing inclusive, i.e. "the
patched release is still vulnerable" — flips **13 of 29 golden verdicts**, including the
lodash 4.17.21 case the README leads with, while **`correctness` stays at 1.0000**. The gate
went red only through one incidental groundedness row on a seed not among the 13.

`golden/oracle_truth.jsonl` — 87 rows derived **by hand** from the OSV spec, never by running
the oracle, weighted toward boundaries — now runs as a separate CI step. Under that bug, 16 of
87 fail.

    eval gate           → orchestration regressions
    oracle truth table  → oracle bugs

## Also in v0.2

- `--repeats N` on both harnesses; LLM claims are a measured spread, not one observation.
- Degenerate deltas print `(identity: identical on all 29)` instead of `[0, 0]`.
- The flip matrix is renamed "verdict-state divergence" — v0.1's single "flip" was an
  abandonment, not a differing security call.
- `LIMITATIONS.md` rewritten to lead with the two disclosures that most change how the
  headline should be read.

## Still not in scope

Full-corpus freeze, crates.io/Go (both declared minimal-fix ecosystems with **zero alerts**
in the corpus), MCP HTTP transport, prompt-injection rail, online evals, LLM-judge
calibration, reachability analysis.
