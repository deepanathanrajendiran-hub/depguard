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

## The merge-blocking eval gate

Two CI workflows run on every push and PR:

- **`ci.yml`** — `pytest` (the unit + integration suite).
- **`eval-gate.yml`** — `python scripts/run_eval.py check`: runs the graph over all
  29 golden inputs and scores them with the §4.1 metrics. It **blocks the merge** if
  the reproducible `deterministic_script` arm drops any aggregate metric below
  `golden/baseline.json`, or if any trajectory's correctness/groundedness falls under
  1.0. This gate guards the scarce asset — the mechanical oracle + verifier + evidence.

  If the `LLM_API_KEY` repo secret is set, the gate also runs the `multi_agent` (LLM)
  arm and fails if *its* correctness/groundedness regress below baseline. The LLM arm
  is intentionally **not** the primary blocker — a non-deterministic merge-gate is an
  anti-pattern; plan-metric noise from the LLM never blocks.

Both jobs should be marked **required** in branch protection (owner's one-time click:
Settings → Branches → protect `main` → require `test` and `eval` status checks).

Regenerate baseline + golden only from an honest run: `python scripts/gen_golden.py`
then `python scripts/run_eval.py baseline` — commit whatever the numbers are, never
rounded up (house rule 2).
