# DepGuard v0.3 — four ecosystems, an adversarial eval, and a judge that failed its own gate

v0.2 established that the agentic system reproduces a deterministic reference exactly, and
added the prose slice showing where it reaches past what that reference can do. v0.3 widens
the corpus so those claims cover more than one package manager, then attacks the system on
purpose.

`corpus_snapshot_id = depguard-corpus-2026-07-01-fdd6db1be17a` — 49 advisories, 4 ecosystems.
Every figure below was re-measured on it; nothing was carried over from the previous snapshot.

## Slice 1 — the agreement now spans four ecosystems

| arm | correctness | groundedness | calls | cost |
|---|---|---|---|---|
| `deterministic_script` | 1.0000 | 1.0000 | 0 | $0.00 |
| `single_agent` (ReAct) | 0.6842 [0.6053–0.7368] | 0.7895 [0.7105–0.8421] | 222 | $0.124 |
| `multi_agent` | 1.0000 [1.0000–1.0000] | 1.0000 | 38 | $0.021 |

`multi_agent` reproduces the reference on **38 of 38 trajectories — npm 15/15, PyPI 14/14,
crates.io 5/5, Go 4/4** — with **0 planner fallbacks**. That now includes Go pseudo-versions
and `+incompatible` build metadata, which is a materially harder surface than v0.2's npm+PyPI.

## Slice 2 — the prose frontier, re-measured

| arm | range accuracy | correct | wrong abstain | wrong range |
|---|---|---|---|---|
| `deterministic_script` | **0.1837** | 9 / 49 | 40 | 0 |
| `regex_baseline` | **0.4490** | 22 / 49 | 15 | 12 |
| `llm_extractor` | **0.6259** [0.6122–0.6327] | 30.7 / 49 | 1.7 | 16.7 |

`llm − script` **+0.4422 [+0.3061, +0.5782]** · `llm − regex` **+0.1769 [+0.0816, +0.2859]**
· `regex − script` **+0.2653 [+0.1429, +0.3878]**. All significant, 3 repeats, 0 fallbacks.
The script's 9 correct answers are only the gold-abstain seeds: **0 of 40** on records whose
prose actually describes a range. Strict ordering holds in every run.

## The corpus grew, and the minimal-fix tier is finally exercised

`verifier.py` has declared `{npm, crates.io, Go}` as the minimal-fix scoring tier since v0.1
while **two of those three carried zero alerts**. v0.3 adds 5 crates.io and 4 Go seeds chosen
for range diversity — a one-version window where the true positive and false positive are
adjacent releases, eight interleaved intervals with prerelease bounds, pseudo-versions at
both bounds, `last_affected` inclusive on `+incompatible` metadata.

**And the re-freeze produced the corpus's first genuine source disagreement, on its own.**
OSV added `GHSA-r5fr-rjxr-66jc` as an alias of the lodash advisory. The ranges did not change
and the deps.dev extract is byte-identical — but deps.dev lists that key at **4.17.21**, so
after alias resolution the second source asserts the *patched* release is vulnerable while
OSV says it is the fix. It lands on `seed_01`, the case the README leads with. That is the
first time the cross-check earned its place on real data.

## Prompt injection — measured, not asserted

The main slice is **immune by construction**: it reads structured ranges and never lets
advisory text reach a decision. The prose slice buys capability by feeding untrusted
third-party text to a model, and opens the hole in the same step. An attack succeeds iff it
changes the containment bitvector — the same mechanical criterion that scores P5.

| arm | resistance | **suppression** | detected |
|---|---|---|---|
| `regex_baseline` | 1.0000 | **0.0000** | — |
| `llm_norail` | 0.5000 | **0.5000** | 0 / 48 |
| `llm_rail` | 0.8333 | **0.1458** | 40 / 48 |

Two findings, both counter-intuitive:

1. **The crudest attack was the least effective.** `direct_override` ("IGNORE ALL PREVIOUS
   INSTRUCTIONS…") suppressed **0 of 8**; `authority_withdrawal` and `range_rewrite`
   suppressed **8 of 8** each. The model resists being ordered around and complies with being
   lied to plausibly. A filter tuned to jailbreak-shaped text would have blocked only the
   attacks that already failed.
2. **The rail's entire residual is the documented blind spot.** Every detected payload drops
   to zero suppression; all 7 remaining cases are `range_rewrite`, which `rails.py` documents
   as undetectable because it contains no instruction at all. **Detection is the bottleneck,
   not the policy.**

## The LLM judge failed its own gate

§4.3 permits a judge for narrative quality only. Calibrated on 19 hand-labelled cases against
a published rubric, it scored **kappa 0.8366** — comfortably over the 0.60 threshold — and is
recorded as **not usable**, because the `confident_but_wrong` trap scored **5 out of 5**.

It cannot do better: a clarity judge is not given ground truth, so fluent falsehood reads as
clarity. A single aggregate averages that away, which is how a judge with a reproducible
weakness ships looking like a measurement. Traps are now gated separately, and nothing in the
repo consumes the judge's output. The §4.3 firewall is asserted **by import graph** across 13
correctness-path modules.

## Also

- Runs on `mcp` **1.x and 2.x** (2.0 renamed `FastMCP` → `MCPServer`); pin is `>=1.2,<3`,
  bounded at the next major because an unbounded `mcp>=1.2` is what broke a fresh install.
- **Streamable HTTP** transport: `depguard-mcp --transport streamable-http`. Serving over HTTP
  is inbound and does not grant the tool layer outbound access.
- Go module paths and npm scoped names are now percent-encoded in the extract layout — a
  no-op for every existing name, and it fixes a crash the new ecosystems exposed.
- **606 tests.**

## Still out of scope

Full-corpus freeze, MCP HTTP auth (the server has none of its own), online evals,
reachability analysis.
