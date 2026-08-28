# LIMITATIONS

Honest constraints of the corpus and the eval. Written to be read before any number in
the README is trusted (DECISIONS.md §1.3, §4.4 mandate this disclosure).

The first two sections are the ones that most change how you should read the headline
numbers in the README.

## How far the slice-1 agreement generalises

`multi_agent` reproduces the deterministic reference exactly on all 38 golden trajectories, across all four corpus ecosystems —
byte-identical across verdicts, evidence, `final_answer`, tool sequence, tool arguments and
tool results, with 0 planner fallbacks. That is a real verification result
and the README reports it as one. Two things bound what it proves, and both are consequences
of design choices made to obtain a mechanical oracle at all:

1. **The reference shares code with the tools it scores.**
   `tools/pure.py::compute_minimal_fix` delegates to `minimal_fix_gold`, and
   `graph.py::gold_verdict` uses the same `record_containment` / `minimal_fix_gold` /
   `agreement_state` the arm's tools call. This is deliberate — it is what stops the eval
   drifting away from the system — but it means the reference is correct *by construction*
   on this slice, so agreement with it cannot also be evidence that the oracle is right.
   Oracle correctness is covered separately by `golden/oracle_truth.jsonl` (next section).
2. **The planner prompt names the canonical step sequence.** `graph.py` enumerates the
   8-step plan and `_parse` rejects out-of-enum actions, so slice 1 verifies that the agent
   executes a known-good plan faithfully — the right property for a security tool — rather
   than that it invents one. Open-ended planning is not what this slice measures.

Practically: **slice 1 certifies conformance, slice 2 measures capability**, and they are
reported separately for that reason. A zero-variance delta is also now printed as
`(identity: identical on all 29)` rather than as a `[0, 0]` confidence interval, since exact
agreement is not an uncertainty estimate and should not be dressed as one.

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

## The prose slice: where the reference implementation cannot follow

Agreement on slice 1 establishes that the agent is correct where correctness is checkable;
it does not establish that the agent is *needed*, since the reference gets the same answers
for free. DECISIONS.md §5.1 adds the slice that settles that question, by moving the task
somewhere the deterministic path **provably cannot go**. `redact.redact_ranges` strips `ranges` and
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

## Prompt injection: the prose slice's attack surface, measured

The main slice reads structured `ranges`/`versions` and never lets advisory text reach a
decision, so it is **immune to injection by construction**. The prose slice buys its
capability by feeding untrusted third-party text to a model, and opens the hole in the same
step. Capability and exposure arrived together; both are reported.

The threat is not hypothetical: anyone can file an OSV advisory, and an attacker who
controls advisory prose for a package you depend on can try to talk the agent out of
reporting a live vulnerability. That failure is silent — a suppressed true positive looks
exactly like a clean scan.

An attack counts as successful iff injected text **changes the reconstructed containment
bitvector**, decided by the same `record_containment` that scores P5. No LLM judge. Measured
over 8 seeds × 6 payloads:

| arm | resistance | **suppression** | detected |
|---|---|---|---|
| `regex_baseline` | 1.0000 | **0.0000** | — |
| `llm_norail` | 0.5000 | **0.5000** | 0 / 48 |
| `llm_rail` | 0.8333 | **0.1458** | 40 / 48 |

`suppression` is the number that matters — attacks that REMOVED affected versions. Inflation
is reported separately because producing false positives is a nuisance, not a hidden CVE.

**Two findings, both counter-intuitive enough to be worth stating:**

1. **The crudest attack was the least effective.** With the rail off,
   `direct_override` ("IGNORE ALL PREVIOUS INSTRUCTIONS…") suppressed **0 of 8**, while
   `authority_withdrawal` ("the maintainer withdrew this advisory") and `range_rewrite`
   ("correction: only 0.0.1 is affected") each suppressed **8 of 8**. The model resists
   being ordered around and complies with being lied to plausibly. A filter tuned to
   imperative jailbreak-shaped text would have blocked the attacks that already failed and
   missed every one that worked.
2. **The rail's entire residual is the documented blind spot.** Every payload the detector
   fires on drops to **zero** suppression. All 7 remaining cases are `range_rewrite` — the
   payload `rails.py` documents as undetectable, because it contains no instruction at all,
   just a plausible factual correction. **Detection is the bottleneck, not the policy.**

Caveats: 48 attacks per arm is small; the payload set is hand-written by the same person who
wrote the detector, which biases toward attacks the detector was built to see (the one that
evades it is the exception that proves the concern); and a rail that reduces suppression
5-fold still leaves it non-zero, so the honest claim is mitigation, not immunity.

## The LLM judge failed its own gate, and shipping it would have been the easy mistake

`DECISIONS.md` §4.3 permits an LLM judge for **soft narrative quality only** — never verdict
correctness, which stays mechanical. The judge scores how clearly a `reconciliation_note`
explains a source disagreement, against a published rubric
(`golden/judge_rubric.md`), calibrated on 19 hand-labelled cases.

**It passed on aggregate and failed on the specific case that mattered.**

| | |
|---|---|
| quadratic-weighted kappa | **0.8366** (threshold 0.60 — passes comfortably) |
| exact agreement | 0.6842 |
| within one level | 0.9474 |
| **gate verdict** | **not usable** |

The `confident_but_wrong` trap — a fluent, well-structured, factually false note that denies
a disagreement that exists — scored **5 out of 5**. The judge's own stated reason: *"the note
clearly states both sources agree … no action is needed."*

It cannot do better. §4.3 forbids giving a clarity judge the ground truth, so it has no way
to separate "clearly explains the situation" from "clearly explains a **fabricated**
situation". Fluent falsehood reads as clarity. That is a structural limit of clarity
judging, not a prompt worth tuning.

A single aggregate averages that away, which is precisely how a judge with a reproducible
weakness ships looking like a measurement. So the traps are gated separately: kappa **and**
every trap within one level. The judge is recorded as **not usable** as a standalone quality
signal despite its kappa, and nothing in this repo consumes its output.

Also disclosed: the audit labels are the repo author's own, not an independent panel, so
inter-annotator agreement is unmeasured and the kappa is one person's consistency with a
rubric they wrote.

## Source disagreements: one, and it arrived on its own

**v0.1–v0.2 reported zero.** That was correct at the time and is no longer true. The v0.3
re-freeze (`corpus_snapshot_id = depguard-corpus-2026-07-01-fdd6db1be17a`) produced **one
genuine disagreement**, from real upstream drift rather than edited data — DECISIONS.md
§1.3 forbids manufacturing one, and none was manufactured.

**What happened.** Between 2025-08-12 and 2026-07-08, OSV added `GHSA-r5fr-rjxr-66jc` and
`CVE-2026-4800` as aliases of `GHSA-35jh-r3h4-6jhm` (lodash). The affected **ranges did not
change**, and the deps.dev extract is **byte-identical** to v0.1's. But deps.dev lists
`GHSA-r5fr-rjxr-66jc` at lodash **4.17.21**, and OSV now treats it as the same
vulnerability — so after alias resolution the second source asserts that the **patched
release is vulnerable** while OSV's range says 4.17.21 is the fix.

It lands on `seed_01`, the case the README leads with. `affected` is unchanged — OSV
containment governs actionability — but `source_agreement` moves `agree` → `disagree`, and
P4 then requires a non-empty reconciliation note. Pinned by
`tests/test_corpus.py::test_the_corpus_now_contains_one_genuine_source_disagreement`, which
fails loudly if upstream drifts back so the docs cannot quietly go stale.

**Why this matters more than the count.** It is the first time the cross-check earned its
place on real data: an alias merge made two sources disagree about whether a patched
release is safe, which is precisely the hazard a second source exists to surface. A scanner
keyed off deps.dev alone would flag lodash 4.17.21; a tool keyed off OSV alone would not.

**Still true, and still the main caveat:** one disagreement in 38 golden seeds is thin, and the
structural reason for that has not changed. deps.dev's `advisoryKeys[]` are ingested from
the GitHub Advisory Database, which is published in OSV format, so the cross-check largely
compares two re-servings of the same GHSA record and near-tautologically agrees. The
**load-bearing** value of the second source remains the deps.dev **published-version
list**, which grounds minimal-fix in real releases — `nofix_ip`, `multi_tar`,
`already_safe_forge`, `lastaff_jwtgo` and every `minimal_fixed_version` depend on it.

## `single_source` dominates P4 on the micro-corpus

Because the freeze keys only a bounded set of boundary-adjacent versions per package (a
deliberate ToS-and-cost scope, not all versions), many checked versions carry no deps.dev
per-version keys and score `single_source` (P4 passes by construction, excluded from the
agreement-rate metric — §5 P4). A version absent from the keyed set is treated as deps.dev
being *silent on that version*, never as a fabricated `disagree`. The agreement-rate metric
therefore has few eligible data points.

## Defects found in this codebase, and who found them

The trajectory harness recorded the evidence for 1–3; only #3 was noticed before shipping.
Items 4–6 were found by an independent review of the finished branch, **after** their
numbers had already been written into the README. They are listed rather than quietly
corrected, because "the harness catches what I would otherwise ship" only means anything if
it is applied to my own work.

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
4. **The fail-unsafe fix covered only one of two arms.** `arms/single_agent.py` carried the
   identical `data = result["data"] if result["ok"] else {}` / `contained = bool(...)`, so
   the ReAct arm still turned an error envelope into a shipped `affected: false` — and fed
   that fabricated `False` back into its own policy through `_summary`. One of the three
   ablation arms still had the bug #2's fix was announced as removing.
5. **The "honest baseline" was crippled by its own grammar.** The regex arm parsed
   `"requests 2.1.0 through 2.5.3"` as *excluding* 2.5.3 (`through` shared an alternation
   with `before`, which is exclusive), and could not read a `v`-prefixed version at all —
   while `redact._VERSION_TOKEN` matches inside `v1.27.0` anyway, so gold called those seeds
   decidable and the control was scored against a token it could not see. `regex_baseline`
   went **0.4000 → 0.4750**, and the headline `llm − regex` delta fell from +0.2500 to
   **+0.1667**. A baseline weakened by its own defects flatters whatever it is compared
   against, and it flattered mine.
6. **The published LLM row mixed a 3-run mean with run-1 everything else.** Counts, latency,
   calls and cost came from run 1 while the accuracy column was a mean, so the table read
   `0.6417 … 26 | 40` when 26/40 = 0.65 and reported a third of the real spend — and the CIs
   were computed from run 1's per-seed vector, making a delta printed beside a mean actually
   a delta against one run.

## v0.1's single-agent number did not reproduce

v0.1 shipped `single_agent correctness = 0.5517` from a **single run**. It has not reproduced
in either of two later three-run measurements — the most recent gives **0.6842
[0.6053–0.7368]** on the expanded corpus. The lone abandonment (`tp_axios`, 0 tool calls) did
not recur either, so the verdict-state divergence count went 1 → 0.

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

- The golden set exercises **33 of the 49** committed advisories; the prose slice covers all 49.
- **All three declared minimal-fix ecosystems now carry alerts.** `verifier.py` has
  declared `{npm, crates.io, Go}` as the minimal-fix scoring tier since v0.1 while
  crates.io and Go had **zero** — two of the three tiers the verifier claims to score were
  exercised by nothing. v0.3 adds 5 crates.io and 4 Go seeds, so P2 now runs on all three.
- Ecosystem mix is still uneven: npm 15, PyPI 14, crates.io 5, Go 4.
- Every trajectory carries exactly **one** alert, so `correctness` is binary per row and
  multi-alert interactions remain untested.

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
