# Prose slice — where the deterministic script provably cannot compete

`corpus_snapshot_id = depguard-corpus-2026-07-01-c6f3471a2245` · 40 seeds (6 gold-abstain)

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
| deterministic_script | 0.1500 | 6 | 40 | 34 | 0 | 0.04 | 0 | $0.0000 | 0 |
| regex_baseline | 0.4750 | 19 | 40 | 11 | 10 | 0.28 | 0 | $0.0000 | 0 |
| llm_extractor | 0.6417 [0.6250–0.6500] | 25.6667 | 40 | 1.66667 | 12.6667 | 642.34 | 120 | $0.2504 | 0 |

_LLM arm run 3x. The bracket is the min–max spread across runs, not a confidence interval. Accuracy and counts are means over runs; latency, calls and cost are TOTALS over every run actually paid for; the paired bootstrap uses each seed's pass rate across runs, so the CI matches the mean it is printed beside._

## Pairwise deltas (paired bootstrap, 10k resamples, 95% CI)

| comparison | Δ range accuracy |
| --- | --- |
| `deterministic_script - regex_baseline` | -0.3250 [-0.4750, -0.1750] * |
| `deterministic_script - llm_extractor` | -0.4917 [-0.6500, -0.3417] * |
| `regex_baseline - llm_extractor` | -0.1667 [-0.2833, -0.0665] * |

`*` marks an interval excluding 0.

