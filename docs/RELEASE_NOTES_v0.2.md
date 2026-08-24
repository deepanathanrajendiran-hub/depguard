# DepGuard v0.2 — the experiment, fixed

v0.1 shipped a headline that could not have come out any other way. This release replaces
it with a measured boundary, and discloses everything the audit that prompted it found.

## Why v0.1's headline was empty

v0.1 led with `deterministic_script ≡ multi_agent`, Δ = `+0.0000`, 95% CI `[0, 0]`, and
presented the tight interval as evidence. It was an **identity**, fixed before any code ran:

- **The script *is* the label function.** `tools/pure.py::compute_minimal_fix` delegates to
  `minimal_fix_gold`, the function that labels gold. On a mechanically decidable task the
  deterministic arm cannot score anything but 1.0000.
- **The planner prompt dictated the plan.** `graph.py` enumerated the canonical 8-step plan
  verbatim; `_parse` rejected anything off-enum. The LLM had no freedom over anything scored.

Measured: the two arms' trajectories are **byte-identical** across verdicts, evidence,
`final_answer`, tool sequence, tool arguments and tool results — 174 tool calls each. The
only differing content is 232 free-text `rationale` strings no metric reads. $0.019 and
147 s bought 232 sentences.

An experiment whose best possible outcome is "no difference" measures nothing.

## The fix: a slice where the script provably cannot compete

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
| `regex_baseline` | **0.4000** | 16 / 40 | 13 | 11 |
| `llm_extractor` | **0.6417** [0.6250–0.6500] | 26 / 40 | 2 | 12 |

`llm − script` **+0.5000 [+0.3500, +0.6500]** · `llm − regex` **+0.2500 [+0.1250, +0.4000]**
· `regex − script` +0.2500 [+0.1250, +0.4000]. All significant. 3 repeats, **0 extractor
fallbacks**, ~$0.08 a run.

The ordering is strict — the LLM wins 10 seeds the regex loses and loses none it wins. The
script's 6 correct answers are only the seeds whose prose names no version at all; on the 34
records that describe a range it scores **0/34**.

**The headline:** a script is free, instant and unbeatable on structured data, and worth
exactly zero the moment the same fact is only in prose. The `regex_baseline` exists so that
"you should have just written the parser" is answered with a number rather than an opinion.

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
