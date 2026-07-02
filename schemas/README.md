# schemas/ — the canonical name registries

These four files are **normative** (DECISIONS.md §0). The MCP server, the golden trajectories, the
OTel `gen_ai.*` attributes, and every metric MUST use exactly these strings. They are committed
artifacts precisely so that naming drift cannot silently mis-score trajectories (DECISIONS.md §9).

| File | Source of truth for | DECISIONS.md |
|---|---|---|
| `ecosystem_system_map.json` | OSV ecosystem ↔ deps.dev system mapping, corpus membership, scoring tiers | §0.4, §1.2, §5(c) |
| `plan_action_tool_map.json` | The `PlanAction` alphabet AND the tool-name alphabet (plan-adherence + tool-selection metrics) | §0.1, §0.2 |
| `tool_key_args.json` | Per-tool scored-argument subsets for the tool-selection-accuracy metric | §2.5 |
| `trajectory.schema.json` | The canonical Trajectory JSON object (the OTel ⇄ eval-harness spine) | §3 |

**One deliberate extension over the frozen spec:** `trajectory.schema.json` allows
`system_variant: "deterministic_script"` (DECISIONS.md §3 lists only `single_agent | multi_agent`),
because the three-arm ablation (docs/DEPGUARD_V01_PLAN.md, D8) requires the deterministic
semver-containment script arm to emit trajectories scored by the same verifier. Flagged in the
schema's `$comment`.

Consistency between these files is enforced by `tests/test_schemas.py` — any edit that breaks
cross-registry agreement fails CI.
