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

Measured over the 29-trajectory golden set (`results/ablation_v01.json`), the
**deterministic semver-containment script** scores `correctness = 1.0000` and
`groundedness = 1.0000`. This is expected and stated numbers-first (house rule 11): the
script calls the *same oracle module* the gold labeler calls, so its verdicts equal gold
by construction. The takeaway is **not** "agents lose" — it is that on the
version-containment slice, under a mechanical oracle, a rule-based script is already at the
ceiling, and the honest question an LLM arm must answer is whether it *matches* that ceiling
without the determinism, not whether it beats it. `action_advancement = 0.1250` reflects
that exactly one of the eight canonical steps per single-alert run advances a *new* verdict
(the metric is defined that way, §4.1.2); it is comparable across arms, not a defect.

**Measured answer (D9, `results/ablation_v01.json`):** the `multi_agent` arm *ties* the
script exactly — `correctness = groundedness = tool_selection = 1.0000`, and the paired
bootstrap on every metric delta (script − multi) is **`+0.0000 [+0.0000, +0.0000]`**, i.e.
the two arms are statistically indistinguishable. The LLM planner buys **nothing** on
accuracy over the rule-based script, at **94.0 s vs 0.57 s wall-clock (≈165×)**. That is the
headline finding, framed numbers-first: the value of DepGuard is the *measurement harness*
that can state this with a CI, not an agent that wins.

## Verdict-flips can only come from omission, not from reconciliation (D9)

In DepGuard's design the LLM's only freedom is *which tools to call*; the verdict logic
(containment, withdrawn override, minimal-fix, `source_agreement`) is the shared oracle,
identical across all three arms. So two arms that both execute the full tool chain emit
*identical* verdicts, and an arm's verdict can differ **only** when it omits or misorders a
tool call (e.g. skipping the cross-check drops `agree` to `single_source`; skipping
containment defaults `affected`). Reconciliation itself never flips a verdict. Combined with
the **0 genuine source-disagreements** already measured in the frozen extract, this predicted
a **verdict-flip count of 0** between the single- and multi-agent arms.

**Confirmed (D9):** the measured flip count is **0**, and the full 3×3 `affected`-
disagreement matrix is all zeros (`results/ablation_v01.json`). Every arm gets the actionable
affected/not-affected call right on all 29 alerts. The `single_agent` arm's *lower*
correctness (0.6897) and groundedness (0.4138) come entirely from skipping the deps.dev
cross-check on some alerts — which corrupts `source_agreement` (`agree` → `single_source`)
and un-grounds the minimal-fix claim — **not** from any different verdict on whether a
package is affected. The distinction matters: the agents differ on *evidence discipline*,
not on the security call.

## The LLM-arm numbers are a single measured run (not bit-reproducible)

The `single_agent` and `multi_agent` figures come from ONE run of DeepSeek (`deepseek-chat`,
temperature 0) over the 29-trajectory golden set. LLM APIs are not bit-reproducible even at
temperature 0, so re-running `python scripts/run_ablation.py` (with a key) may shift the
single-agent aggregates by a few points; the deterministic_script arm and every CI computed
against it are exactly reproducible. The **script − multi_agent** CIs are degenerate by
construction — both arms score a constant `1.0` per trajectory on correctness/groundedness,
so the delta has zero variance and the interval collapses to `[0, 0]`; that is reported
as-is, not smoothed, and is itself the finding (the arms are indistinguishable). Cost/latency
are the machine's measured wall-clock, in the markdown report only.
