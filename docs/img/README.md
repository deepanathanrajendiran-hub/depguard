# Images for the README (owner captures these)

Two screenshots/GIFs the README references. They are owner-captured because they need live
accounts/tools the build environment lacks; until dropped in, the README links are
placeholders.

- **`langfuse-trace.png`** — a Langfuse trace of one demo triage (a `depguard.triage` root
  span + one `execute_tool` child per tool call). How to produce and capture it:
  see `docs/DEPLOY.md` → "Capture the Langfuse trace screenshot".

- **`red-ci.gif`** — the merge-blocking eval gate going **red** on a planner regression.
  How to produce it: delete the `cross_check_source` step from `deterministic_plan` in
  `depguard/graph.py` (correctness → 0.45, groundedness → 0.14, gate fails). Open a PR,
  screen-record the failing Actions run, save the GIF here, close the PR unmerged.
