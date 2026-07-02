"""The Trajectory builder + validator (DECISIONS.md §3, the OTel⇄eval spine).

Pure and LLM-free: assembles the §3 object incrementally, stores tool-call
envelopes verbatim, joins everything on `alert_id`, and validates against
`schemas/trajectory.schema.json` in `build()` — a trajectory that fails validation
RAISES (`TrajectoryInvalid`). `gold_ref = sha256(canonical-JSON of input)` (§4.5).

Timestamps and span/trace ids are DETERMINISTIC (derived from the trajectory id +
a step counter) so committed golden trajectories are byte-stable. Real OTel span
ids replace the derived ones in D6, mirrored 1:1 (§3.1).
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "trajectory.schema.json"


class TrajectoryInvalid(Exception):
    """A built trajectory failed schema validation (§3)."""


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def gold_ref_for(trajectory_input: dict) -> str:
    """§4.5 join key: sha256 of the canonical input {manifest, alerts}."""
    return hashlib.sha256(canonical_json(trajectory_input).encode("utf-8")).hexdigest()


def _hex(*parts: str, width: int) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:width]


def _ts(n: int) -> str:
    """Deterministic RFC3339 stamp for step n (frozen corpus ⇒ wall-clock is meaningless)."""
    return f"2026-07-01T00:{(n // 60) % 60:02d}:{n % 60:02d}Z"


class TrajectoryBuilder:
    def __init__(
        self,
        *,
        system_variant: str,
        model_route: str,
        corpus_snapshot_id: str,
        trajectory_input: dict,
    ):
        self.system_variant = system_variant
        self.model_route = model_route
        self.corpus_snapshot_id = corpus_snapshot_id
        self.input = trajectory_input
        self.gold_ref = gold_ref_for(trajectory_input)
        self.trajectory_id = f"traj-{self.gold_ref[:12]}-{system_variant}"
        self._plan: list[dict] = []
        self._tool_calls: list[dict] = []
        self._evidence: list[dict] = []
        self._verdicts: list[dict] = []
        self._n = 0  # monotonic step counter for deterministic time/span ids

    # -- plan -------------------------------------------------------------- #
    def add_plan_step(self, action, alert_id, rationale, status="planned",
                      produced_verdict_for=None) -> dict:
        step = {
            "step_index": len(self._plan),
            "action": action,
            "alert_id": alert_id,
            "rationale": rationale,
            "status": status,
            "produced_verdict_for": produced_verdict_for,
        }
        self._plan.append(step)
        return step

    def mark_executed(self, step_index, produced_verdict_for=None) -> None:
        step = self._plan[step_index]
        step["status"] = "executed"
        if produced_verdict_for is not None:
            step["produced_verdict_for"] = produced_verdict_for

    # -- tool calls -------------------------------------------------------- #
    def add_tool_call(self, *, agent, tool_name, arguments, result, source) -> str:
        i = self._n
        self._n += 1
        span_id = _hex(self.trajectory_id, "span", str(i), width=16)
        tc_id = f"tc-{i:03d}"
        self._tool_calls.append({
            "tool_call_id": tc_id,
            "span_id": span_id,
            "parent_span_id": _hex(self.trajectory_id, "root", width=16),
            "agent": agent,
            "tool_name": tool_name,
            "tool_type": "function",
            "arguments": arguments,
            "result": result,
            "status": "ok" if result.get("ok") else "error",
            "started_at": _ts(i),
            "ended_at": _ts(i + 1),
            "source": source,
            "corpus_snapshot_id": self.corpus_snapshot_id,
        })
        return tc_id

    # -- evidence ---------------------------------------------------------- #
    def add_evidence(self, row: dict) -> str:
        self._evidence.append(row)
        return row["evidence_id"]

    # -- verdicts ---------------------------------------------------------- #
    def add_verdict(self, verdict: dict) -> None:
        self._verdicts.append(verdict)

    # -- build ------------------------------------------------------------- #
    def build(self) -> dict:
        n_alerts = len(self.input.get("alerts", []))
        n_tp = sum(1 for v in self._verdicts if v["affected"])
        traj = {
            "schema_version": "1.0.0",
            "trajectory_id": self.trajectory_id,
            "created_at": _ts(0),
            "system_variant": self.system_variant,
            "model_route": self.model_route,
            "corpus_snapshot_id": self.corpus_snapshot_id,
            "gold_ref": self.gold_ref,
            "otel": {
                "trace_id": _hex(self.trajectory_id, "trace", width=32),
                "root_span_id": _hex(self.trajectory_id, "root", width=16),
            },
            "input": self.input,
            "plan": self._plan,
            "tool_calls": self._tool_calls,
            "evidence": self._evidence,
            "verdicts": self._verdicts,
            "final_answer": {
                "verdicts_summary": {
                    "n_alerts": n_alerts,
                    "n_true_positive": n_tp,
                    "n_false_positive": n_alerts - n_tp,
                },
                "per_alert": [
                    {"alert_id": v["alert_id"], "affected": v["affected"],
                     "minimal_fixed_version": v["minimal_fixed_version"]}
                    for v in self._verdicts
                ],
                "emitted_at": _ts(self._n + 1),
            },
        }
        try:
            jsonschema.validate(
                traj, _schema(),
                format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
            )
        except jsonschema.ValidationError as exc:
            raise TrajectoryInvalid(
                f"trajectory {self.trajectory_id} failed §3 schema validation at "
                f"{list(exc.absolute_path)}: {exc.message}"
            ) from exc
        return traj
