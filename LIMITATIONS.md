# LIMITATIONS

Honest constraints of the corpus and the eval. Written to be read before any number in
the README is trusted (DECISIONS.md §1.3, §4.4 mandate this disclosure).

The first two sections are the ones that most change how you should read the headline.

## The main slice is decidable, so its "tie" was an identity, not a finding

The v0.1 headline was `deterministic_script ≡ multi_agent`, Δ = `+0.0000`, 95% CI `[0,0]`
on every metric. That is not a tight estimate. It is a **diff of a function against
itself**, and it was fixed before any code ran, for two independent reasons:

1. **The script IS the label function.** `tools/pure.py::compute_minimal_fix` delegates to
   `minimal_fix_gold`, and `graph.py::gold_verdict` computes gold with the same
   `record_containment` / `minimal_fix_gold` / `agreement_state` the arm's tools call. On
   a mechanically decidable task there is no possible world short of a serialization bug
   in which the deterministic arm scores anything but `1.0000`.
2. **The planner prompt dictated the plan.** `graph.py` enumerates the canonical 8-step
   plan verbatim, and `_parse` rejects out-of-enum actions and coerces unknown alert_ids
   to `None`, so `multi_agent` had no degrees of freedom over anything scored.

Measured consequence: the `deterministic_script` and `multi_agent` trajectories are
**byte-identical** across verdicts, evidence, `final_answer`, tool sequence, tool
arguments *and* tool results — 174 tool calls each. The only differing content is 232
free-text `rationale` strings that no metric reads. $0.019 and 147 seconds bought 232
sentences.

So the multi-agent arm's ceiling was a tie. `paired_bootstrap_delta` now returns
`degenerate=True` for a zero-variance delta vector and the report prints
`(identity: identical on all 29)` rather than `[0, 0]`, so the identity can no longer be
mistaken for a measurement. **The prose slice (below) is the fix for the experiment; this
section is the disclosure for the old one.**

## The eval gate cannot catch oracle bugs — only orchestration regressions

`scripts/run_eval.py` recomputes gold with `build_gold()` at gate time, and the tools
share the oracle with the labeler. Prediction and label therefore move **together**, and
the coupling the README used to sell as anti-drift has a corollary: a bug *inside* the
oracle is invisible to the gate.

This was measured, not assumed. Inverting one line in `depguard/oracle.py` — making a
`fixed` event close inclusive instead of exclusive, a real semver bug meaning "the patched
release is still vulnerable" — produces:

- **13 of 29 golden verdicts change.** All six false-positive seeds invert to
  `affected=True`, including `seed_01` (lodash 4.17.21 — the case the README leads with),
  which then recommends 4.17.23.
- **`correctness` stays at `1.0000`.** Not one seed fails it.
- The gate goes red only through a single incidental `groundedness` row on
  `tp_cross_spawn`, a seed that is not among the 13. It caught that bug by luck.

`golden/oracle_truth.jsonl` closes the hole: 87 rows derived **by hand** from each
advisory's range events against the OSV spec, never by running the oracle, weighted toward
boundaries (the `fixed` release itself, `last_affected`, multi-range gaps, PEP 440
prereleases like `5.2b1` and `2.0.0rc1`, numeric-vs-lexical ordering like 1.10.0 vs
1.9.3). Under the injected bug, 16 of 87 rows fail. It runs as a **separate** CI step.

    eval gate           → orchestration regressions (plan, tools, evidence)
    oracle truth table  → oracle bugs

The shared oracle remains the scorer — that design is right, and it is what stops the eval
drifting away from the tools. What changed is that it is no longer the *only* thing
watching the oracle.

## The prose slice: where the script provably cannot compete

Because the main slice could only ever produce a tie, DECISIONS.md §5.1 adds a slice where
the deterministic path **provably fails**. `redact.redact_ranges` strips `ranges` and
`versions` from the frozen records — a pure function of already-frozen bytes, so
`corpus_snapshot_id` is unchanged and every main-slice number stays reproducible — leaving
the affected range only in the `details` prose. Every entry in `E_A` then abstains and
`record_containment` **raises**; that is an exception asserted by a committed test, not a
contested number.

Caveats specific to this slice:

- **P5 defines equivalence relative to the frozen published list.** A reconstruction that
  differs from gold only where no release exists (`last_affected: 5.1.2` vs
  `fixed: 5.2b1`) scores as correct. That is deliberate — containment over real releases
  is the only thing the verdict and minimal-fix consume — but it does mean P5 is a
  behavioural equivalence, not a claim that the model recovered the advisory's exact text.
- **Gold-abstain is a regex, not a judgement.** A record counts as gold-ABSTAIN iff its
  prose carries no version token. That is mechanical and byte-reproducible, but it is a
  crude proxy: prose could name a version and still be too vague to reconstruct.
- **The regex baseline is one person's best effort**, not a proof of the ceiling for
  non-LLM approaches. A better grammar would raise it. It exists so the rebuttal "you
  should have just written the parser" is answered with a number instead of an opinion.
- 40 seeds, one package per advisory. Small.

## Zero genuine source-disagreements in the frozen corpus

Searching every keyed `(advisory, version)` pair in the frozen deps.dev extract
(`corpus_snapshot_id = depguard-corpus-2026-07-01-c6f3471a2245`) yields **0 cases where
deps.dev's per-version advisory keys contradict OSV's computed containment.**

This is the predicted result, not a defect (DECISIONS.md §1.3): deps.dev's
`advisoryKeys[]` are ingested from the GitHub Advisory Database, which is published in OSV
format — so the cross-check largely compares two re-servings of the same GHSA record and
near-tautologically agrees. **We do NOT manufacture a `disagree` case by editing data.**

Consequences, stated plainly:

- The **`source_agreement` cross-check adds no independent second opinion** on this corpus,
  and the measured verdict-flip count from reconciliation is **0**. That is the finding for
  the cross-check dimension, not a number to hide. The P4 `disagree` branch — including its
  requirement that a `disagree` verdict carry a non-empty `reconciliation_note` — is
  therefore exercised only by a synthetic fixture (`tests/fixtures/disagree_corpus/`),
  never by real corpus data.
- The **load-bearing** value of the second source is the deps.dev **published-version
  list**, which grounds minimal-fix in real releases. Golden cases `nofix_ip`, `multi_tar`,
  `already_safe_forge` and every `minimal_fixed_version` depend on it — that is genuine
  independence.

## `single_source` dominates P4 on the micro-corpus

Because the freeze keys only a bounded set of boundary-adjacent versions per package (a
deliberate ToS-and-cost scope, not all versions), many checked versions carry no deps.dev
per-version keys and score `single_source` (P4 passes by construction, excluded from the
agreement-rate metric — §5 P4). A version absent from the keyed set is treated as deps.dev
being *silent on that version*, never as a fabricated `disagree`. The agreement-rate metric
therefore has few eligible data points.

## Two fail-unsafe defects the harness caught, and one it did not

The trajectory harness recorded all three; only the third was noticed before shipping.

1. **`verdicts_summary` dismissed unanswered alerts.** `trajectory.py::build()` computed
   `n_false_positive = n_alerts - n_true_positive`, so any alert a run failed to answer
   silently became a false positive. The shipped v0.1 `single_agent` run on seed `tp_axios`
   abandoned with **0 tool calls, 0 evidence and 0 verdicts** and emitted
   `{n_alerts: 1, n_true_positive: 0, n_false_positive: 1}` against a gold of
   `affected=True` — **a genuine CVE reported as dismissed by a run that did no work.**
   Fixed: the summary is derived from emitted verdicts only, and the gap is reported as
   `n_unresolved`. `n_true_positive + n_false_positive + n_unresolved == n_alerts`, always.
2. **An error envelope became "not affected".** `Pipeline._exec_check` took
   `result["data"] if result["ok"] else {}` and then set `contained` from it, so *any* tool
   error resolved to `affected=False`. Most visibly, an unpinned `^4.17.0` manifest entry
   was reported **NOT AFFECTED** when all DepGuard had established was that it could not
   parse the version. Fixed: undecidable alerts emit no verdict and surface as
   `n_unresolved`. (Corpus curation currently filters the records that would reach this by
   other routes, so it was latent rather than live — but it is the same class as #1.)
3. **`action_advancement` was an inverted metric.** It was |steps advancing a new alert| /
   |executed steps|, which on a one-alert-per-trajectory corpus reduces to
   `1 / n_executed_steps` — it scored an arm *higher* for doing less work:

   | action_advancement | n | mean correctness |
   |---|---|---|
   | 0.2500 (best) | 9 | 0.333 (worst) |
   | 0.1667 | 13 | 0.538 |
   | 0.1429 (worst) | 6 | **1.000** |

   Within-arm correlation with correctness: **−0.172**. `results/ablation_v01.md`
   consequently marked the *deterministic* arm "significantly worse" on it than an arm that
   answered 13 of 29 alerts wrong. Replaced by `verdict_yield` (distinct alerts verdicted /
   alerts given): invariant to step count, monotone with quality, and it makes abandonment
   a loss rather than a win. The deterministic arm moves 0.125 → 1.0.

## v0.1's single-agent number did not reproduce

v0.1 shipped `single_agent correctness = 0.5517` from a **single run**. Three fresh runs
under `--repeats 3` give **0.7931 / 0.6552 / 0.7931** (mean 0.7471). The published figure
sits *outside* that entire range. Groundedness moved 0.6207 → 0.8046 [0.7931–0.8276]. The
lone abandonment (`tp_axios`, 0 tool calls) did not recur, so the verdict-state divergence
count went 1 → 0.

Nothing about the arm changed to cause this — it is ordinary LLM run-to-run variance on a
29-item set, which is exactly what an n=1 measurement cannot see. Treat every LLM figure in
this repo as one of a handful of samples, and note that a 3-run min–max spread is still not
a confidence interval: with n=3 it understates the true variance substantially.

## What the single-agent arm actually gets wrong

This is the one slice-1 finding that **reproduced**, and it got stronger. Its failures are
**evidence discipline, not security judgment**:

- On every alert it answered, its actionable affected/not-affected call was **correct** —
  28/28 in v0.1, **29/29** in the re-run — and so was `withdrawn`. It has never
  misclassified a package in any measured run.
- It skips the deps.dev cross-check. `crosscheck_second_source` went unrun on **12 of 29**
  alerts in the re-run and **22 of 29** in v0.1, taking `source_agreement` down with it.
  That 12-vs-22 gap is the point: the *direction* of this finding is stable across runs,
  the *magnitude* is not, so any rate quoted here is one sample.
- Correctness and groundedness **diverge in both directions** — in the re-run, 5
  trajectories scored correct with groundedness 0.0 (the right answer, not entailed by the
  evidence actually gathered) and 6 the inverse. No aggregate accuracy number can show that,
  and it is the clearest argument for keeping per-trajectory rows.
- v0.1's **1 verdict-flip vs multi_agent** was an **abandonment, not a misjudgment**: on
  `tp_axios` the agent called 0 tools and emitted no verdict, which the matrix counts as
  differing from multi's `affected = True`. It did not recur.

## Metric-scope caveat: the main-slice metrics measure instruction-following

On the main slice the multi_agent planner prompt enumerates the expected per-alert tool
sequence verbatim, and the byte-diff above shows the arm deviates from the script on
**nothing that is scored**. So for verdicts, evidence, minimal-fix and tool sequence these
metrics measure instruction-following under heavy scaffolding — not partly, entirely.
`plan_adherence` and `tool_selection` in particular confirm the scaffold was followed. The
prose slice is where the metrics have something else to measure, because there the prompt
cannot contain the answer.

## Corpus utilisation

- The golden set exercises **26 of the 40** committed advisories, across 24 packages.
- `verifier.py` declares `{npm, crates.io, Go}` as the minimal-fix scoring tier, but the
  corpus contains **zero crates.io and zero Go alerts** — two of the three minfix
  ecosystems are entirely untested.
- Every trajectory carries exactly **one** alert, so `correctness` is binary per row and
  multi-alert interactions are untested.

## Scope caveats

- Corpus is **npm + PyPI only**, 40 hand-picked advisories — a branch-coverage fixture,
  NOT a representative sample. The `all.zip` full freeze + crates.io/Go are backlog.
- The **71–90% scanner-false-positive** figure cited elsewhere is driven largely by
  call-graph *reachability* analysis, which DepGuard deliberately does not perform. DepGuard
  addresses only the version-range-containment slice of triage.
- **Frozen snapshot, not a live scanner.** All advisory/version data is a committed 2026-07
  snapshot (`corpus_snapshot_id` on every evidence row); the tools never touch the network.
  Verdicts reflect that snapshot's accuracy, not today's advisory database.
- **Sandbox tools, not a real upgrade.** DepGuard *names* the minimal safe upgrade from the
  published-version list; it does not apply it, run the project's tests against it, or check
  transitive/peer-dependency compatibility.

## Reproducibility of the LLM arms

The deterministic arm and every figure computed from it are exactly reproducible. LLM APIs
are not bit-reproducible even at temperature 0, so LLM figures shift between runs. Both
`scripts/run_ablation.py` and `scripts/run_prose_slice.py` take `--repeats N` and report a
min–max spread; a spread is **not** a confidence interval, and with small N it understates
the true variance. Cost is **derived** from measured token counts at DeepSeek's published
rate; tokens and latency are measured. Raw per-arm trajectories and per-trajectory metric
rows are persisted under `results/` so any figure here is checkable post hoc.

## No LLM judge in the correctness path

Correctness, groundedness and P5 are **100% mechanical** — the same oracle labels gold and
scores predictions, and P5 compares containment bitvectors produced by one identical
`record_containment` call on both sides. DECISIONS.md §4.3 reserves a *calibrated* LLM
judge for soft narrative quality only (e.g. the readability of a `reconciliation_note`),
never for verdict correctness; that judge is **not built**. No result here depends on an
LLM grading an LLM.
