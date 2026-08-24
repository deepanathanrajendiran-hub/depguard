# DepGuard v0.1 — three-arm ablation

- corpus_snapshot_id: `depguard-corpus-2026-07-01-c6f3471a2245`
- golden trajectories: 29  ·  alerts: 29
- arms run: deterministic_script, single_agent, multi_agent

## Per-arm metrics (mean over the golden set)

| arm | tool_selection | verdict_yield | plan_adherence | groundedness | correctness | latency (s) | LLM calls | tokens | cost (USD) | fallbacks |
|---|---|---|---|---|---|---|---|---|---|
| deterministic_script | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.57 | 0 | 0 | $0.0000 | 0 |
| single_agent | 0.8970 | 1.0000 | 0.5402 | 0.8276 | 0.7931 | 781.86 | 175 | 143,498 | $0.1017 | 0 |
| multi_agent | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 113.85 | 29 | 21,636 | $0.0170 | 0 |

_cost at DeepSeek published pricing $0.27/$1.1 per 1M input/output tokens; tokens are measured, cost is derived._

## Pairwise paired-bootstrap 95% CI on Δ (arm_A − arm_B)
_10,000 resamples, seed 0; `*` = interval excludes 0._

| pair | tool_selection | verdict_yield | plan_adherence | groundedness | correctness |
|---|---|---|---|---|---|
| deterministic_script − single_agent | +0.1030 [+0.0554, +0.1547] * | +0.0000 (identity: identical on all 29) | +0.4598 [+0.4425, +0.4770] * | +0.1724 [+0.0345, +0.3103] * | +0.2069 [+0.0690, +0.3793] * |
| deterministic_script − multi_agent | +0.0000 (identity: identical on all 29) | +0.0000 (identity: identical on all 29) | +0.0000 (identity: identical on all 29) | +0.0000 (identity: identical on all 29) | +0.0000 (identity: identical on all 29) |
| single_agent − multi_agent | -0.1030 [-0.1547, -0.0554] * | +0.0000 (identity: identical on all 29) | -0.4598 [-0.4770, -0.4425] * | -0.1724 [-0.3103, -0.0345] * | -0.2069 [-0.3793, -0.0690] * |

## Verdict-state divergence matrix

_Counts alerts whose verdict STATE differs. Emitting no verdict is its own state, so an abandonment counts here without either arm having made a differing security judgement — read the footnote before calling a non-zero cell a disagreement._

| A ⧵ B | deterministic_script | single_agent | multi_agent |
|---|---|---|---|
| deterministic_script | 0 | 0 | 0 |
| single_agent | 0 | 0 | 0 |
| multi_agent | 0 | 0 | 0 |

**Divergence count (multi_agent vs single_agent): 0**

_Planner fallbacks: 0 across all arms — the multi_agent numbers reflect genuine LLM planning, not a silent fall-through to the deterministic script._

