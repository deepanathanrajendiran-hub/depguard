# DepGuard v0.1 — three-arm ablation

- corpus_snapshot_id: `depguard-corpus-2026-07-01-c6f3471a2245`
- golden trajectories: 29  ·  alerts: 29
- arms run: deterministic_script, single_agent, multi_agent

## Per-arm metrics (mean over the golden set)

| arm | tool_selection | action_advancement | plan_adherence | groundedness | correctness | latency (s) |
|---|---|---|---|---|---|---|
| deterministic_script | 1.0000 | 0.1250 | 1.0000 | 1.0000 | 1.0000 | 0.57 |
| single_agent | 0.9206 | 0.1650 | 0.5259 | 0.4138 | 0.6897 | 184.76 |
| multi_agent | 1.0000 | 0.1250 | 1.0000 | 1.0000 | 1.0000 | 94.04 |

## Pairwise paired-bootstrap 95% CI on Δ (arm_A − arm_B)
_10,000 resamples, seed 0; `*` = interval excludes 0._

| pair | tool_selection | action_advancement | plan_adherence | groundedness | correctness |
|---|---|---|---|---|---|
| deterministic_script − single_agent | +0.0794 [+0.0533, +0.1118] * | -0.0400 [-0.0503, -0.0318] * | +0.4741 [+0.4598, +0.4885] * | +0.5862 [+0.4138, +0.7586] * | +0.3103 [+0.1379, +0.4828] * |
| deterministic_script − multi_agent | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] | +0.0000 [+0.0000, +0.0000] |
| single_agent − multi_agent | -0.0794 [-0.1118, -0.0533] * | +0.0400 [+0.0318, +0.0503] * | -0.4741 [-0.4885, -0.4598] * | -0.5862 [-0.7586, -0.4138] * | -0.3103 [-0.4828, -0.1379] * |

## Verdict-flip matrix (alerts whose actionable `affected` differs)

| A ⧵ B | deterministic_script | single_agent | multi_agent |
|---|---|---|---|
| deterministic_script | 0 | 0 | 0 |
| single_agent | 0 | 0 | 0 |
| multi_agent | 0 | 0 | 0 |

**Flip count (multi_agent vs single_agent): 0**

