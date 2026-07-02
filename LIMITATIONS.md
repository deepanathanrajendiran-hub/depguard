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
