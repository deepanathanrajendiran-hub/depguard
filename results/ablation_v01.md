# DepGuard v0.1 — three-arm ablation

- corpus_snapshot_id: `depguard-corpus-2026-07-01-fdd6db1be17a`
- golden trajectories: 38  ·  alerts: 38
- arms run: deterministic_script, single_agent, multi_agent

## LLM-arm repeat spread

_The table below is a SINGLE run. LLM APIs are not bit-reproducible even at temperature 0, so an n=1 figure is an observation, not a propensity. These are the same arms re-run end to end._

| arm | runs | correctness (mean) | min | max | groundedness (mean) | min | max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| single_agent | 3 | 0.6842 | 0.6053 | 0.7368 | 0.7895 | 0.7105 | 0.8421 |
| multi_agent | 3 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |

_A min-max spread over a handful of runs is not a confidence interval and understates the true variance._

## Per-arm metrics (mean over the golden set)

| arm | tool_selection | verdict_yield | plan_adherence | groundedness | correctness | latency (s) | LLM calls | tokens | cost (USD) | fallbacks |
|---|---|---|---|---|---|---|---|---|---|
| deterministic_script | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.03 | 0 | 0 | $0.0000 | 0 |
| single_agent | 0.8767 | 1.0000 | 0.5373 | 0.8158 | 0.7105 | 962.64 | 222 | 177,211 | $0.1240 | 0 |
| multi_agent | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 154.10 | 38 | 27,350 | $0.0211 | 0 |

_cost at DeepSeek published pricing $0.27/$1.1 per 1M input/output tokens; tokens are measured, cost is derived._

## Pairwise paired-bootstrap 95% CI on Δ (arm_A − arm_B)
_10,000 resamples, seed 0; `*` = interval excludes 0._

| pair | tool_selection | verdict_yield | plan_adherence | groundedness | correctness |
|---|---|---|---|---|---|
| deterministic_script − single_agent | +0.1233 [+0.0805, +0.1695] * | +0.0000 (identity: identical on all 38) | +0.4627 [+0.4496, +0.4759] * | +0.1842 [+0.0789, +0.3158] * | +0.2895 [+0.1579, +0.4474] * |
| deterministic_script − multi_agent | +0.0000 (identity: identical on all 38) | +0.0000 (identity: identical on all 38) | +0.0000 (identity: identical on all 38) | +0.0000 (identity: identical on all 38) | +0.0000 (identity: identical on all 38) |
| single_agent − multi_agent | -0.1233 [-0.1695, -0.0805] * | +0.0000 (identity: identical on all 38) | -0.4627 [-0.4759, -0.4496] * | -0.1842 [-0.3158, -0.0789] * | -0.2895 [-0.4474, -0.1579] * |

## Verdict-state divergence matrix

_Counts alerts whose verdict STATE differs. Emitting no verdict is its own state, so an abandonment counts here without either arm having made a differing security judgement — read the footnote before calling a non-zero cell a disagreement._

| A ⧵ B | deterministic_script | single_agent | multi_agent |
|---|---|---|---|
| deterministic_script | 0 | 0 | 0 |
| single_agent | 0 | 0 | 0 |
| multi_agent | 0 | 0 | 0 |

**Divergence count (multi_agent vs single_agent): 0**

_Planner fallbacks: 0 across all arms — the multi_agent numbers reflect genuine LLM planning, not a silent fall-through to the deterministic script._

