# DepGuard

[![CI](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/ci.yml)
[![eval-gate](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/eval-gate.yml/badge.svg?branch=main)](https://github.com/deepanathanrajendiran-hub/depguard/actions/workflows/eval-gate.yml)

Most dependency-vulnerability alerts are false alarms. A scanner flags a pinned version as
vulnerable, an engineer spends an afternoon proving it isn't, and the cycle repeats. DepGuard
reads each alert and decides whether the pinned version is actually inside the advisory's
affected range, shows the advisory evidence it used, and names the smallest safe upgrade. Every
verdict is checked by a mechanical verifier, so I can report how often each system gets it right
with a confidence interval instead of a vibe.

## What I measured

Triage over a frozen advisory corpus is mechanically decidable: a plain semver-containment
pipeline solves it with no LLM at all. That makes it a good place to ask a question people
usually hand-wave, which is whether an agent actually beats the deterministic version and how
you'd prove it either way.

I ran three arms over the same 29 golden trajectories (a frozen npm + PyPI micro-corpus), scored
by the same 4-predicate verifier with no LLM judge anywhere in the correctness path. LLM arms use
DeepSeek `deepseek-v4-flash` at temperature 0; CIs are a 10,000-sample paired bootstrap.

| arm | correctness | groundedness | tool-selection | latency | cost | LLM calls |
|---|---|---|---|---|---|---|
| `deterministic_script` | 1.0000 | 1.0000 | 1.0000 | 0.5 s | $0.00 | 0 |
| `single_agent` (ReAct) | 0.5517 | 0.6207 | 0.8213 | 1002 s | $0.114 | 159 |
| `multi_agent` (planner→executor) | 1.0000 | 1.0000 | 1.0000 | 147 s | $0.019 | 29 |

Pairwise deltas, 95% CI, straight from [`results/ablation_v01.json`](results/ablation_v01.json):

| Δ | correctness | groundedness | tool-selection |
|---|---|---|---|
| `script − multi_agent` | +0.0000 [0, 0] | +0.0000 [0, 0] | +0.0000 [0, 0] |
| `multi_agent − single_agent` | +0.448 [0.276, 0.621] | +0.379 [0.207, 0.552] | +0.179 [0.116, 0.261] |

A few things stand out.

The multi-agent system ties the script exactly. Every delta is 0.0000 with a CI of [0, 0]. The
interval is that tight because both arms produce identical verdicts on a decidable task, so every
per-trajectory difference is zero and the bootstrap has nothing to spread. The LLM planner buys
no accuracy here, and it costs $0.019 and 147 seconds per run against free and half a second.

The tie is real, not an accident of plumbing. A planner that fails to produce a valid plan can
quietly fall back to the deterministic one and post a fake 1.0, so I count those fallbacks and
stamp them into the trajectory's `model_route`. There were zero across all 29 multi-agent runs.

The single agent is the more interesting result. It's worse everywhere, but not because it gets
the security call wrong: on the 28 alerts where it returned a verdict, its affected/not-affected
judgment was correct every time. It loses points on evidence it skipped: on 12 alerts it dropped
the deps.dev cross-check, so `source_agreement` fell to `single_source`, and 6 of those also got
the minimal fix wrong; on one more it gave up without answering. So the scaffolding buys
completeness, not better judgment.

If there's a headline, it's the harness that can state all of this with a CI, not the agent.
Every number above comes from [`results/`](results/) (metrics and CIs in the JSON, latency in the
[report](results/ablation_v01.md), raw trajectories in [`results/trajectories/`](results/trajectories/)).
Read [LIMITATIONS.md](LIMITATIONS.md) before you trust any of it. Short version: on a decidable
task these metrics partly measure whether the agent follows a scaffolded prompt, and the two LLM
rows are a single run, not a bit-reproducible one.

## The gate

A merge-blocking CI job (`scripts/run_eval.py`, `.github/workflows/eval-gate.yml`) re-scores the
deterministic arm on every push and fails the build if correctness or groundedness slips below the
committed baseline. Deleting one step from the planner drops correctness to 0.45 and groundedness
to 0.14, and CI goes red with a gold-vs-actual trajectory diff. To reproduce, delete the
`cross_check_source` step from `deterministic_plan` in `depguard/graph.py` and run
`python scripts/run_eval.py check`.
<!-- TODO: add docs/img/red-ci.gif once recorded from a real PR run -->

## Tracing

Each trajectory is replayed as OpenTelemetry GenAI spans that line up 1:1 with the tool calls, and
exported to Langfuse when the keys are set (`depguard/otel.py`). You get a `depguard.triage` root
span with one `execute_tool` child per call, tagged with the standard `gen_ai.*` attributes.
<!-- TODO: add docs/img/langfuse-trace.png once captured (see docs/DEPLOY.md) -->

## Quickstart

```bash
pip install -e .

# 1. CLI: triage a manifest against the frozen corpus (no key, no network)
depguard-triage examples/package.json
#   AFFECTED      alert-0-GHSA-35jh-r3h4-6jhm   GHSA-35jh-r3h4-6jhm → fix 4.17.21
#   AFFECTED      alert-2-GHSA-3xgq-45jj-v275   GHSA-3xgq-45jj-v275 → fix 7.0.5
#   not affected  alert-3-GHSA-2328-f5f3-gj25
#   # 4 of 7 alert(s) actually affected
# (or point it at your own package.json — out-of-corpus deps fall back to a canned demo lockfile)

# 2. Web demo: paste a package.json, watch verdicts stream in
pip install -e ".[demo]" && uvicorn depguard.webapp:app --port 8080   # http://localhost:8080

# 3. Reproduce the ablation (the LLM arms need a DeepSeek key; the script arm doesn't)
python scripts/run_ablation.py
```

Cloud Run and the Langfuse capture steps are in [docs/DEPLOY.md](docs/DEPLOY.md).

## MCP server

The six tools are also a stdio MCP server that any client can install:

```bash
claude mcp add depguard -- depguard-mcp
```

Claude Desktop config and the full tool list are in [docs/MCP.md](docs/MCP.md).

## How it works

```
manifest + scanner alerts
        │
   planner ── retriever ── tool_worker ── verifier ──► one Verdict per alert
  (rule or LLM)   │            │             │          affected? · minimal fix · evidence
                  └──── six typed {ok,data,error} tools ────┘
                        (the same code labels gold and scores predictions)
```

For each alert DepGuard answers three things: is the pinned version actually in the advisory's
affected range, what's the authoritative advisory plus the exact range-event evidence, and what's
the smallest published version that clears it (grounded in the deps.dev version list, never
invented). The containment and minimal-fix logic a tool uses is the same module that labels the
gold answers and that the verifier scores against, so the eval can't quietly drift away from the
tools.

Ground truth is a committed OSV + deps.dev snapshot
(`corpus_snapshot_id = depguard-corpus-2026-07-01-c6f3471a2245`) stamped on every evidence row;
the verifier refuses to score across a snapshot mismatch, and nothing in the tool layer touches
the network. One thing I'm upfront about: the 71–90% scanner false-positive figures you see quoted
are mostly about call-graph reachability, which DepGuard doesn't attempt. This handles the
version-range-containment slice, which is the part with a mechanical ground truth. The design is
frozen in [DECISIONS.md](DECISIONS.md).

## Limitations

Read [LIMITATIONS.md](LIMITATIONS.md) first. It covers the degenerate CIs, the single LLM run, the
instruction-following-under-scaffolding caveat, the zero genuine source-disagreements in the
corpus, the npm+PyPI scope, and the reachability caveat above.

## License and data

Code is MIT. OSV records are CC0-1.0 or CC-BY-4.0 (GHSA-origin records keep their attribution);
deps.dev-derived rows are CC-BY-4.0 with per-row provenance. The corpus is a frozen snapshot, so
verdicts reflect the snapshot date rather than live advisory data. See `NOTICE/ATTRIBUTION.md`
(generated by the freeze job) and DECISIONS.md §1.7.
