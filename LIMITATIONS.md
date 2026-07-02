# LIMITATIONS

Honest constraints of the v0.1 micro-corpus + eval. Written to be read before any
number in the README is trusted (DECISIONS.md §1.3, §4.4 mandate this disclosure).

## Zero genuine source-disagreements in the frozen corpus

Searching every keyed `(advisory, version)` pair in the frozen deps.dev extract
(`corpus_snapshot_id = depguard-corpus-2026-07-01-c6f3471a2245`) yields **0 cases
where deps.dev's per-version advisory keys contradict OSV's computed containment.**

This is the predicted result, not a defect (DECISIONS.md §1.3): deps.dev's
`advisoryKeys[]` are ingested from the GitHub Advisory Database, which is published
in OSV format — so the advisory-key cross-check largely compares two re-servings of
the same GHSA record and near-tautologically agrees. **We do NOT manufacture a
`disagree` case by editing data.**

Consequences, stated plainly:

- The **`source_agreement` cross-check adds no independent second opinion** on this
  corpus. When the D8–D9 ablation reports the verdict-flip count from reconciliation,
  the expected honest answer is **0 flips**, and that is the headline finding for the
  cross-check dimension, not a number to hide.
- The **load-bearing** value of the second source is the deps.dev **published-version
  list**, which grounds minimal-fix in real releases. Golden cases `nofix_ip`,
  `multi_tar`, `already_safe_forge`, and every `minimal_fixed_version` depend on it —
  that is genuine independence, and it is what the multi-agent arm buys.

## `single_source` dominates P4 on the micro-corpus

Because the freeze keys only a bounded set of boundary-adjacent versions per package
(a deliberate ToS-and-cost scope, not all versions), many checked versions carry no
deps.dev per-version keys and score `single_source` (P4 passes by construction,
excluded from the agreement-rate metric — §5 P4). A version absent from the keyed
set is treated as deps.dev being *silent on that version*, never as a fabricated
`disagree`. The agreement-rate metric therefore has few eligible data points in v0.1.

## Scope caveats

- Corpus is **npm + PyPI only**, 40 hand-picked advisories — a branch-coverage
  fixture, NOT a representative sample. The `all.zip` full freeze + crates.io/Go are
  v0.2 (`docs/DEPGUARD_BACKLOG.md`).
- The **71–90% scanner-false-positive** figure cited elsewhere is driven largely by
  call-graph *reachability* analysis, which DepGuard deliberately does not perform.
  DepGuard addresses only the version-range-containment slice of triage.

## The deterministic script arm ties the ceiling — by construction (D9)

Measured over **29 golden trajectories on a frozen npm+PyPI micro-corpus**
(`results/ablation_v01.json`), the **deterministic semver-containment script** scores
`correctness = groundedness = tool_selection = 1.0000`. This is expected and stated
numbers-first (house rule 11): the script calls the *same oracle module* the gold labeler
calls, so its verdicts equal gold by construction. The takeaway is **not** "agents lose" —
it is that on the version-containment slice, under a mechanical oracle, a rule-based script
is already at the ceiling, and the honest question an LLM arm must answer is whether it
*matches* that ceiling without the determinism, not whether it beats it.
`action_advancement = 0.1250` reflects that exactly one of the eight canonical steps per
single-alert run advances a *new* verdict (the metric is defined that way, §4.1.2); it is
comparable across arms, not a defect.

**Measured answer (D9):** the `multi_agent` arm *ties* the script exactly —
`correctness = groundedness = tool_selection = 1.0000`, **0 planner fallbacks** (see below),
and the paired bootstrap on every metric delta (script − multi) is
**`+0.0000 [+0.0000, +0.0000]`**. That interval is **degenerate by construction**: both arms
score a constant `1.0` per trajectory, so every per-trajectory delta is *identically* zero
and the bootstrap collapses to a point — exactly what two deterministic-toolchain arms
emitting identical verdicts on a decidable task must produce. It is reported as-is, not
smoothed, and the collapse *is* the finding: the arms are statistically indistinguishable.
The LLM planner buys **nothing** on accuracy over the rule-based script — at **147 s /
\$0.019 / 29 LLM calls vs 0.5 s / \$0.00 / 0 calls** end-to-end (incl. API round-trips). The
value of DepGuard is the *measurement harness* that can state this with a CI, not an agent
that wins.

## The multi_agent tie is genuine, not a silent fallback (D9)

A multi_agent arm scoring a perfect `1.0` could be the interesting result ("a
planner→executor scaffold recovers determinism on a decidable task") **or** an artifact (the
LLM planner failed twice and quietly ran the deterministic plan — `graph.py`). Both produce
*identical* numbers, so the harness instruments the difference: `LLMPlanner.fell_back`, a
fallback counter, and a `planner-fallback→deterministic` suffix stamped into `model_route`.
**Measured: `planner_fallbacks = 0` across all 29 multi_agent runs** — the tie is real LLM
planning, not a fall-through to the script.

## What the single-agent arm actually gets wrong (D9)

The `single_agent` arm (one ReAct loop, no planner) scores `correctness = 0.5517`,
`groundedness = 0.6207`, at **1002 s / \$0.114 / 159 LLM calls** — significantly worse on
every metric (single − multi correctness `−0.448 [−0.621, −0.276]`). *How* it is worse
matters, and it is **not** the security call:

- On the **28 of 29** alerts where it emitted a verdict, its `affected` (actionable
  affected/not-affected) judgment is **correct on all 28** — it never misclassifies a package.
- Its correctness misses are entirely **metadata from skipped steps**: `source_agreement`
  wrong on **12** (it skipped the deps.dev cross-check → `single_source` instead of `agree`),
  `minimal_fixed_version` wrong on **6** (it skipped resolve/minfix).
- The **1 verdict-flip vs multi_agent** (`flip_count_multi_vs_single = 1`) is an
  **abandonment, not a misjudgment**: on `tp_axios` the agent called **0 tools and emitted no
  verdict at all**, which the flip matrix counts as differing from multi's `affected = True`.

So the multi-agent scaffold's measured value here is **completeness and never giving up** —
not better security judgment.

## Metric-scope caveat: instruction-following under scaffolding (D9)

The multi_agent planner prompt *enumerates* the expected per-alert tool sequence, so on this
task `plan-adherence` and `tool-selection` partly measure **instruction-following under heavy
scaffolding**, not open-ended planning. Harder inputs (multi-alert manifests where ordering
is non-obvious) or a more open prompt are where those two metrics would begin to discriminate;
in v0.1 they mostly confirm the scaffold is followed.

## The LLM-arm numbers are a single measured run (not bit-reproducible)

The `single_agent` and `multi_agent` figures are ONE run of DeepSeek (`deepseek-v4-flash`,
temperature 0) over the golden set. LLM APIs are not bit-reproducible even at temperature 0,
so re-running `python scripts/run_ablation.py` (with a key) will shift the single-agent
aggregates (an earlier run — before the metric-denominator fix and on the deprecated
`deepseek-chat` alias — read `0.69` correctness; this one reads `0.55`). The
deterministic_script arm and every CI computed against it are exactly reproducible. The raw
per-arm trajectories and per-trajectory metric rows are persisted under `results/` as the
audit trail, so any figure here is checkable post-hoc. Cost is **derived** from measured
token counts at DeepSeek's published rate (stated in the report); tokens and latency are
measured.

## Other v0.1 scope notes

- **No LLM judge in the correctness path.** Correctness and groundedness are **100%
  mechanical** — the same oracle labels gold and scores predictions. DECISIONS.md §4.3
  reserves a *calibrated* LLM judge for **soft narrative quality only** (e.g. the readability
  of a `reconciliation_note`), never for verdict correctness; that judge is **not built in
  v0.1**. So no result here depends on an LLM grading an LLM.
- **Frozen snapshot, not a live scanner.** All advisory/version data is a committed 2026-07
  snapshot (`corpus_snapshot_id` on every evidence row); the tools never touch the network.
  Verdicts reflect that snapshot's accuracy, not today's advisory database — a real deployment
  would re-freeze on a schedule and diff snapshots. The demo says this in the UI.
- **Sandbox tools, not a real upgrade.** DepGuard *names* the minimal safe upgrade from the
  published-version list; it does not apply it, run the project's tests against it, or check
  transitive/peer-dependency compatibility. Acting on the verdict is out of v0.1 scope.
