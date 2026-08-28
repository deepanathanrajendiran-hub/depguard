# Prose slice — where the deterministic script provably cannot compete

`corpus_snapshot_id = depguard-corpus-2026-07-01-fdd6db1be17a` · 49 seeds (9 gold-abstain)

The v0.1 ablation ran on a mechanically decidable task, so the script scored
1.0000 by construction and the LLM arms could at best tie. Here the affected
range is redacted out of the frozen records and survives only in the advisory
prose, which no grammar recovers. `record_containment` RAISES on a redacted
record, so the script's failure is a raised exception, not a contested number.

Scoring is P5 SEMANTIC-RANGE-EQUIVALENCE and stays 100% mechanical: the claim is
materialised against the frozen published-version list and compared to the
unredacted record by containment bitvector, running the SAME
`record_containment` on both sides. No LLM judge anywhere.

## Per-arm range accuracy

| arm | range accuracy | correct | scored | wrong abstain | wrong range | latency (s) | LLM calls | cost | fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic_script | 0.1837 | 9 | 49 | 40 | 0 | 0.09 | 0 | $0.0000 | 0 |
| regex_baseline | 0.4490 | 22 | 49 | 15 | 12 | 3.83 | 0 | $0.0000 | 0 |
| llm_extractor | 0.6259 [0.6122–0.6327] | 30.6667 | 49 | 1.66667 | 16.6667 | 539.35 | 147 | $0.3038 | 0 |

_LLM arm run 3x. The bracket is the min–max spread across runs, not a confidence interval. Accuracy and counts are means over runs; latency, calls and cost are TOTALS over every run actually paid for; the paired bootstrap uses each seed's pass rate across runs, so the CI matches the mean it is printed beside._

## Pairwise deltas (paired bootstrap, 10k resamples, 95% CI)

| comparison | Δ range accuracy |
| --- | --- |
| `deterministic_script - regex_baseline` | -0.2653 [-0.3878, -0.1429] * |
| `deterministic_script - llm_extractor` | -0.4422 [-0.5782, -0.3061] * |
| `regex_baseline - llm_extractor` | -0.1769 [-0.2859, -0.0816] * |

`*` marks an interval excluding 0.

