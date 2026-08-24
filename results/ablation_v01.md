# DepGuard v0.1 — three-arm ablation

- corpus_snapshot_id: `depguard-corpus-2026-07-01-c6f3471a2245`
- golden trajectories: 29  ·  alerts: 29
- arms run: deterministic_script, single_agent, multi_agent

## Per-arm metrics (mean over the golden set)

| arm | tool_selection | action_advancement | plan_adherence | groundedness | correctness | latency (s) | LLM calls | tokens | cost (USD) | fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic_script | 1.0000 | 0.1250 | 1.0000 | 1.0000 | 1.0000 | 0.53 | 0 | 0 | $0.0000 | 0 |
| single_agent | 0.8213 | 0.1819 | 0.5259 | 0.6207 | 0.5517 | 1002.26 | 159 | 139,785 | $0.1142 | 0 |
| multi_agent | 1.0000 | 0.1250 | 1.0000 | 1.0000 | 1.0000 | 147.48 | 29 | 21,567 | $0.0188 | 0 |

_cost at DeepSeek published pricing $0.27/$1.1 per 1M input/output tokens; tokens are measured, cost is derived._

## Pairwise paired-bootstrap 95% CI on Δ (arm_A − arm_B)
_10,000 resamples, seed 0; `*` = interval excludes 0._

| pair | tool_selection | action_advancement | plan_adherence | groundedness | correctness |
|---|---|---|---|---|---|
| deterministic_script − single_agent | +0.1787 [+0.1160, +0.2612] * | -0.0569 [-0.0766, -0.0363] * | +0.4741 [+0.4368, +0.5230] * | +0.3793 [+0.2069, +0.5517] * | +0.4483 [+0.2759, +0.6207] * |
| deterministic_script − multi_agent | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| single_agent − multi_agent | -0.1787 [-0.2612, -0.1160] * | +0.0569 [+0.0363, +0.0766] * | -0.4741 [-0.5230, -0.4368] * | -0.3793 [-0.5517, -0.2069] * | -0.4483 [-0.6207, -0.2759] * |

## Verdict-flip matrix (alerts whose actionable `affected` differs)

| A ⧵ B | deterministic_script | single_agent | multi_agent |
|---|---|---|---|
| deterministic_script | 0 | 1 | 0 |
| single_agent | 1 | 0 | 1 |
| multi_agent | 0 | 1 | 0 |

**Flip count (multi_agent vs single_agent): 1**

_Planner fallbacks: 0 across all arms — the multi_agent numbers reflect genuine LLM planning, not a silent fall-through to the deterministic script._

