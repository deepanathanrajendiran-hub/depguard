# DepGuard v0.1

A dependency-CVE false-positive triage agent, measured under a **100%-mechanical verifier**.
The headline is the eval + observability harness, not the agent.

## The measured result (29 golden trajectories, frozen npm+PyPI micro-corpus)

A three-arm ablation scored by the same 4-predicate mechanical verifier, paired-bootstrap
95% CIs (10k resamples):

| arm | correctness | groundedness | latency | cost |
|---|---|---|---|---|
| `deterministic_script` | 1.0000 | 1.0000 | 0.5 s | $0.00 |
| `single_agent` | 0.5517 | 0.6207 | 1002 s | $0.114 |
| `multi_agent` | 1.0000 | 1.0000 | 147 s | $0.019 |

- **`deterministic_script` ≡ `multi_agent`**: Δ = **+0.0000, 95% CI [0, 0]** on every metric —
  statistically indistinguishable, with **0 planner fallbacks** (instrumented, so the tie is
  genuine LLM planning). The LLM planner buys nothing on accuracy over a free, sub-second script.
- **`multi_agent` ≫ `single_agent`**: correctness +0.448 [0.276, 0.621]. The single agent's
  failures are evidence discipline (12 `source_agreement` + 6 npm-scored minimal-fix misses) + 1
  abandonment — **never a wrong affected/not-affected call** on the 28 verdicts it emitted.
- Full numbers + raw trajectory audit trail: `results/`. Honest caveats: `LIMITATIONS.md`.

## What's in v0.1

- Frozen npm+PyPI micro-corpus (40 advisories, byte-reproducible freeze, deps.dev derived
  extract, `corpus_snapshot_id = depguard-corpus-2026-07-01-c6f3471a2245`).
- Six typed tools on a `{ok,data,error}` envelope; the shared-oracle 4-predicate verifier
  (same code labels gold and scores predictions).
- LangGraph planner→retriever→tool_worker→verifier; three ablation arms emitting one
  trajectory schema.
- 29 golden trajectories + a **merge-blocking eval gate** (a one-line planner regression →
  correctness 0.45 / groundedness 0.14 → CI red).
- Typed **MCP server** (stdio, 6 tools); **CLI** (`depguard-triage`) + **web demo** (SSE,
  coverage-aware fallback); **OpenTelemetry GenAI** spans → Langfuse (1:1).

## Not in v0.1 (gated backlog — `docs/DEPGUARD_BACKLOG.md`)

Full-corpus freeze, crates.io/Go, MCP HTTP transport, prompt-injection rail + red-team eval,
online evals, LLM-judge calibration, Cloud Run auto-deploy, packaging. No dates until v0.1
ships and the job-search gate opens.

## Tag (owner)

```bash
git tag v0.1 && git push --tags
# then create the GitHub release, pasting the table above
```
