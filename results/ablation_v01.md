# DepGuard v0.1 — three-arm ablation

- corpus_snapshot_id: `depguard-corpus-2026-07-01-c6f3471a2245`
- golden trajectories: 29  ·  alerts: 29
- arms run: deterministic_script
- **arms pending (require `LLM_API_KEY`): single_agent, multi_agent** — re-run `python scripts/run_ablation.py` with a DeepSeek key to fill these in.

## Per-arm metrics (mean over the golden set)

| arm | tool_selection | action_advancement | plan_adherence | groundedness | correctness | latency (s) |
|---|---|---|---|---|---|---|
| deterministic_script | 1.0000 | 0.1250 | 1.0000 | 1.0000 | 1.0000 | 0.53 |

## Pairwise paired-bootstrap 95% CI on Δ (arm_A − arm_B)
_10,000 resamples, seed 0; `*` = interval excludes 0._

_pending — only one arm ran; no pairwise comparison possible yet._

## Verdict-flip matrix (alerts whose actionable `affected` differs)

| A ⧵ B | deterministic_script |
|---|---|
| deterministic_script | 0 |

**Flip count (multi_agent vs single_agent): pending — LLM arms not run**

