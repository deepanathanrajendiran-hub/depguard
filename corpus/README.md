# corpus/ — the frozen v0.1 micro-corpus

**`corpus_snapshot_id`: `depguard-corpus-2026-07-01-c6f3471a2245`**  ·  capture 2026-07-01

The runtime tool layer and CI read ONLY this directory — never the network
(DECISIONS.md §1.4). Regenerate with `python scripts/freeze_micro.py`.

## What this is (and is not)

A deliberately SMALL, hand-picked npm + PyPI slice (40 advisories)
chosen to exercise every branch of the mechanical verifier — NOT a representative
sample of the vulnerability landscape and NOT a benchmark leaderboard. The full
`gs://osv-vulnerabilities/all.zip` freeze is a v0.2 item (DECISIONS.md editorial
note 3); v0.1 hashes these record bytes ‖ the deps.dev extract bytes ‖ the
curation-ruleset tag.

## Selection criteria

Every advisory was fetched by id from `api.osv.dev`, curated per §1.2 with the
runtime comparators (`depguard.comparators`), and kept only if it survives in
exactly one corpus ecosystem. Package popularity was a selection filter so each
name resolves on deps.dev; the set was seeded to include the §4.2 categories:
true-positives, scanner false-positives, withdrawn advisories, no-fix-available,
already-safe, and multi-`affected[]` records.

## Counts (pinned post-freeze)

| Metric | Value |
|---|---|
| total records | 40 |
| by ecosystem | {'npm': 18, 'PyPI': 22} |
| withdrawn | 6 |
| CC-BY-4.0 / CC0-1.0 | 37 / 3 |
| deps.dev packages | 42 |

- withdrawn: GHSA-56pw-mpj4-fxww, GHSA-7fhm-mqm4-2wp7, GHSA-9959-c6q6-6qp3, GHSA-crvj-3gj9-gm2p, GHSA-h4pw-wxh7-4vjj, GHSA-j7j6-7hfx-5522
- multi-`affected[]`: GHSA-24wv-mv5m-xv4h, GHSA-29mw-wpgm-hmr9, GHSA-2gwj-7jmv-h26r, GHSA-35jh-r3h4-6jhm, GHSA-3g43-6gmg-66jw, GHSA-3jfq-g458-7qm9, GHSA-3xgq-45jj-v275, GHSA-43f8-2h32-f4cj, GHSA-7fhm-mqm4-2wp7, GHSA-q34m-jh98-gwm2

## Layout

```
corpus/
  osv/<ECOSYSTEM>/<ID>.json          curated OSV record: surviving affected[]
                                     entries only, each annotated scoring_tier,
                                     plus _provenance {source,license,url,retrieved}
  depsdev_extract/<system>/<name>.json   DERIVED extract (§1.7b): published-version
                                     list + bounded (version -> advisory-key) table.
                                     NEVER raw deps.dev response bodies (ToS §5).
  SNAPSHOT.lock                      capture_date, corpus_snapshot_id, per-file
                                     sha256, curation_ruleset_version, capture window
  README.md                          this file
NOTICE/ATTRIBUTION.md                auto-generated CC-BY attribution
```

## Reproducibility

Re-running on 2026-07-01 reproduces identical bytes unless upstream
data changed (OSV may re-issue a `modified` timestamp; deps.dev may publish new
versions). Any such drift changes `corpus_snapshot_id` and is expected — old gold
labels pin to the old id (DECISIONS.md §1.4, §6).
