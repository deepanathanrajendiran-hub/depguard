# DepGuard

> Security scanners cry wolf — most dependency-vulnerability alerts are false alarms, and
> engineering teams burn days triaging them by hand. **DepGuard** decides which alerts are
> *actually* real — citing the exact advisory range — and names the smallest safe upgrade.
> Every verdict is checked by a **100%-mechanical verifier**, so we can say *exactly* how
> often each system is right, with a confidence interval.

## The result (measured, not claimed)

Dependency-alert triage over a frozen advisory corpus is *mechanically decidable* — a
deterministic semver-containment pipeline solves it with no LLM. That is exactly why it is a
good testbed: it lets you ask **when an agent actually adds value over a solved pipeline, and
prove the answer.** DepGuard runs a three-arm ablation, all three arms emitting the
[same trajectory format](schemas/trajectory.schema.json) and scored by the **same 4-predicate
mechanical verifier** (no LLM judge in the correctness path).

**On 29 golden trajectories over a frozen npm + PyPI micro-corpus** (DeepSeek
`deepseek-v4-flash`, temperature 0; paired bootstrap, 10 000 resamples, 95% CI):

| arm | correctness | groundedness | tool-selection | latency | cost | LLM calls |
|---|---|---|---|---|---|---|
| `deterministic_script` | **1.0000** | **1.0000** | 1.0000 | 0.5 s | **$0.00** | 0 |
| `single_agent` (ReAct) | 0.5517 | 0.6207 | 0.8213 | 1002 s | $0.114 | 159 |
| `multi_agent` (planner→executor) | **1.0000** | **1.0000** | 1.0000 | 147 s | $0.019 | 29 |

Pairwise Δ (95% CI), from [`results/ablation_v01.json`](results/ablation_v01.json):

| Δ | correctness | groundedness | tool-selection |
|---|---|---|---|
| `script − multi_agent` | **+0.0000 [0, 0]** | **+0.0000 [0, 0]** | **+0.0000 [0, 0]** |
| `multi_agent − single_agent` | +0.448 [0.276, 0.621] | +0.379 [0.207, 0.552] | +0.179 [0.116, 0.261] |

**What this says, numbers-first:**

- **The LLM planner buys *nothing* on accuracy over the rule-based script.** `multi_agent`
  ties `deterministic_script` exactly, and the paired-bootstrap delta on every metric is
  `+0.0000 [0, 0]`. That interval is *degenerate by construction* — both arms score a constant
  `1.0` per trajectory, so every per-trajectory delta is identically zero and the bootstrap
  collapses to a point. That collapse **is** the finding: the arms are indistinguishable, at
  **$0.00 / 0.5 s vs $0.019 / 147 s.**
- **The tie is genuine, not a silent fallback.** A planner that fails can quietly run the
  deterministic plan and fake a perfect score; DepGuard instruments this
  (`planner_fallbacks`, a `model_route` suffix). Measured: **0 fallbacks across all 29
  `multi_agent` runs** — real LLM planning.
- **Structure, not the LLM, is what preserves quality.** The `single_agent` ReAct arm (same
  six tools, no planner) is significantly worse on every metric. Its failures are **not the
  security call**: on the 28/29 alerts where it emitted a verdict, its affected/not-affected
  judgment is correct on all 28. The gap is *evidence discipline* — 12 wrong
  `source_agreement` (skipped cross-checks) + 6 wrong minimal-fix (skipped resolve/fix) — and
  **one abandonment** (it called 0 tools on one alert and emitted no verdict; that is the sole
  `multi − single` verdict-flip).

The deliverable is the **measurement harness that can state all of this with a CI**, not an
agent that wins. Every number above traces to
[`results/ablation_v01.json`](results/ablation_v01.json) / [`.md`](results/ablation_v01.md),
backed by the raw per-arm trajectories in [`results/trajectories/`](results/trajectories/).
Read [LIMITATIONS.md](LIMITATIONS.md) before trusting any of it — including that these metrics
partly measure *instruction-following under scaffolding* on this decidable task, and that the
LLM-arm numbers are a single (non-bit-reproducible) run.

## The gate that keeps it honest

A merge-blocking CI eval (`scripts/run_eval.py`, `.github/workflows/eval-gate.yml`) re-scores
the deterministic arm on every push and **fails the build** if correctness or groundedness
drops below the committed baseline. Breaking one planner line drops correctness to 0.45 /
groundedness to 0.14 → gate red (see `docs/notes-for-d12.md`).
<!-- red-CI GIF: docs/img/red-ci.gif (owner-captured) -->

## Observability

Each trajectory is replayed **1:1** as OpenTelemetry GenAI spans and exported to Langfuse when
keys are set (`depguard/otel.py`). A `depguard.triage` root span carries one `execute_tool`
child per tool call with literal `gen_ai.*` semconv attributes.
<!-- Langfuse trace: docs/img/langfuse-trace.png (owner-captured; see docs/DEPLOY.md) -->

## Quickstart

```bash
pip install -e .

# 1. CLI — triage a manifest against the frozen corpus (no key, no network)
depguard-triage package.json
#   AFFECTED   alert-0-GHSA-35jh-r3h4-6jhm  GHSA-35jh-r3h4-6jhm → fix 4.17.21
#   WITHDRAWN  alert-1-GHSA-7fhm-mqm4-2wp7  GHSA-7fhm-mqm4-2wp7

# 2. Web demo — "paste your package.json" (streams verdicts over SSE)
pip install -e ".[demo]" && uvicorn depguard.webapp:app --port 8080   # → http://localhost:8080

# 3. Reproduce the ablation (LLM arms need a DeepSeek key; the script arm doesn't)
python scripts/run_ablation.py
```

Cloud Run deploy + Langfuse capture: [docs/DEPLOY.md](docs/DEPLOY.md).

## MCP server

The six tools are published as a typed **MCP server** (stdio) any stock client can install:

```bash
claude mcp add depguard -- depguard-mcp        # Claude Code
```

Full install / Claude Desktop config: [docs/MCP.md](docs/MCP.md).

## How it works (design frozen in [DECISIONS.md](DECISIONS.md))

```
manifest + scanner alerts
        │
   planner ── retriever ── tool_worker ── verifier ──► Verdict[] (one per alert)
   (rule or LLM)   │            │             │         affected? · minimal fix · evidence
                   └──── six typed {ok,data,error} tools ────┘
                         (the SAME oracle labels gold AND scores predictions)
```

- **Per alert:** (a) is the pinned version *actually* inside the advisory's affected range?
  (b) the authoritative advisory + exact range-event evidence, (c) the minimal *published*
  safe upgrade, grounded in the deps.dev version list.
- **Shared oracle:** the containment / minimal-fix / agreement logic used by a tool is the
  *same module* that labels gold and that the verifier scores against — the eval cannot drift
  from the oracle.
- **Frozen ground truth:** a committed OSV + deps.dev snapshot
  (`corpus_snapshot_id = depguard-corpus-2026-07-01-c6f3471a2245`) on every evidence row; the
  verifier refuses to score across a snapshot mismatch. No network in the tool layer.
- **Scope we state up front:** the widely-cited 71–90% scanner false-positive rates are driven
  mostly by *reachability* analysis, which DepGuard deliberately does not do. DepGuard
  addresses the version-range-containment slice — the slice with mechanical ground truth.

## Limitations

The honest constraints — degenerate CIs, the single measured LLM run, instruction-following
under scaffolding, zero genuine source-disagreements in the micro-corpus, npm+PyPI scope, and
the reachability caveat — are in **[LIMITATIONS.md](LIMITATIONS.md)**. Read it first.

## License & data

Code: MIT. Advisory data: OSV records are CC0-1.0 or CC-BY-4.0 (GHSA-origin records preserve
attribution); deps.dev-derived rows are CC-BY-4.0 with per-row provenance. The committed corpus
is a frozen snapshot — verdicts reflect the snapshot date, not live advisory accuracy. See
`NOTICE/ATTRIBUTION.md` (generated by the freeze job) and DECISIONS.md §1.7.
