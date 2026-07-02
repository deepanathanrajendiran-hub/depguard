"""The three-arm ablation. All three arms emit the SAME
schema-valid §3 Trajectory so one verifier + one metrics module score them:

- `deterministic_script` — the deterministic semver-containment script (no LLM); the frozen
  reference that reproduces the committed golden trajectories byte-for-byte.
- `single_agent`        — one ReAct loop holding all six tools (no supervisor/planner).
- `multi_agent`         — the LangGraph planner→retriever→tool_worker→verifier (LLM planner);
  lives in depguard.graph (run_graph(..., system_variant="multi_agent")).
"""

from depguard.arms.script_arm import run_script_arm
from depguard.arms.single_agent import run_single_agent

__all__ = ["run_script_arm", "run_single_agent"]
