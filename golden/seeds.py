"""Golden-set seed INPUTS (the source of truth; trajectories + expected are
generated from these by scripts/gen_golden.py). Each value is a §3 trajectory
`input` {manifest, alerts}. Grows across D5 (seed_01) → D6 (~10) → D7 (25–30)."""

SEED_INPUTS = {
    # D5 headline: scanner flags lodash 4.17.21 for CVE-2021-23337, but 4.17.21 is
    # the FIXED release ([0, 4.17.21) is exclusive) → a false positive (affected=False).
    "seed_01": {
        "manifest": [
            {"ecosystem": "npm", "name": "lodash", "pinned_version": "4.17.21",
             "purl": "pkg:npm/lodash@4.17.21"}
        ],
        "alerts": [
            {"alert_id": "seed_01-a1", "ecosystem": "npm", "name": "lodash",
             "pinned_version": "4.17.21", "advisory_id": "GHSA-35jh-r3h4-6jhm",
             "source": "scanner"}
        ],
    },
}
