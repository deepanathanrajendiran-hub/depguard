# Contributing / house rules

This is a solo portfolio project, but it runs under rules designed to keep it honest and shipping.

## The three ground rules

1. **No `DECISIONS.md` amendment without an attached failing test.** The design is frozen at v1.3.0.
   If implementation contradicts it, write the failing test first, commit it, then amend the decision
   in the same PR with a `schema_version` bump where interfaces change. Spec-vs-spec editing rounds
   are banned — code contact resolves open questions.
2. **No un-measured number ships anywhere** — README, docs, demo, resume. A metric may only appear
   together with (or after) the committed run that produced it. Honest negative results (e.g., the
   deterministic script tying the agents, a verdict-flip count of zero) are reported in LIMITATIONS,
   not hidden.
3. **The schema registries in `schemas/` are normative.** Tools, golden trajectories, OTel attributes,
   and metrics must use exactly those strings. `tests/test_schemas.py` enforces cross-registry
   consistency in CI; if you need a new name, change the registry and the test in the same commit.

## Dev setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

CI runs `pytest` on every push and PR; the merge-blocking golden-trajectory eval gate lands in Phase 1 (D7).
