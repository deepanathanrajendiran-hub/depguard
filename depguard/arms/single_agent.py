"""The `single_agent` ablation arm (docs/HANDOFF_D8-D14.md §D8).

ONE ReAct-style loop holding all six tools — NO supervisor and NO separate planner
(contrast `multi_agent`, which has an LLM planner feeding a fixed executor). The agent's
only freedom is WHICH tool to call and in WHAT ORDER; typed arguments are bound
mechanically from the alert + accumulated tool outputs (the six tools are strongly typed,
so there is nothing to hallucinate). Because there is no executor to re-order or backfill
missing calls, a bad ordering self-sabotages (calling a compute tool before its advisory is
retrieved is skipped) — that missing-safety-net IS the structural difference the ablation
measures against `multi_agent`.

Each executed tool decision is reverse-mapped to a §0.2 PlanAction (so plan-adherence is
computable); there is NO run-level `plan` step (a ReAct agent emits no plan-as-data).
Verdicts are emitted by the SAME `assemble_verdict` rule all three arms share.

Policy interface (two kinds, unified in `run_single_agent`):
  * batch    — a callable `policy(trajectory_input) -> list[decision]` (scripted: the
               `canonical_policy`/`lazy_policy` reference chains that drive the arm
               deterministically in keyless CI).
  * interactive — any object exposing `.next(observation) -> decision | None`, driven in a
               real observe→act loop. `LLMReactPolicy` (DeepSeek, house rule 9) is the live
               arm, used only when LLM_API_KEY is set (D9's ablation run).
A `decision` is `{"tool": <tool_name|"__done__">, "alert_id": <str|None>}`.
"""

from __future__ import annotations

import json
import os

from depguard.graph import (
    _find_record,
    assemble_verdict,
    depsdev_evidence_row,
    osv_evidence_row,
)
from depguard.snapshot import Snapshot
from depguard.tools.external import (
    crosscheck_second_source,
    osv_query_package,
    resolve_published_versions,
)
from depguard.tools.pure import (
    check_version_affected,
    compute_minimal_fix,
    parse_manifest,
)
from depguard.trajectory import TrajectoryBuilder

ARM = "single_agent"

# reverse of build_gold's action→tool map (§0.2 registry): tool_name → PlanAction
_TOOL_TO_ACTION = {
    "parse_manifest": "parse_manifest",
    "osv_query_package": "retrieve_advisory",
    "resolve_published_versions": "resolve_versions",
    "check_version_affected": "check_containment",
    "compute_minimal_fix": "compute_minimal_fixed",
    "crosscheck_second_source": "cross_check_source",
}
# action → executing agent (§3 toolCall.agent enum). A single agent has one logical role,
# but the schema requires one of the four role names; we label by tool CATEGORY. This is
# metric-neutral — no metric reads `agent` — and keeps the trajectory schema-valid.
_RETRIEVER_ACTIONS = {"parse_manifest", "retrieve_advisory", "resolve_versions"}

_RATIONALE = {
    "parse_manifest": "parse the dependency manifest",
    "retrieve_advisory": "fetch OSV advisories",
    "resolve_versions": "list published versions",
    "check_containment": "is the pinned version in the affected range?",
    "compute_minimal_fixed": "smallest published safe upgrade",
    "cross_check_source": "reconcile against deps.dev",
    "emit_verdict": "emit the reconciled verdict",
}


# --------------------------------------------------------------------------- #
# reference policies (scripted, deterministic — no LLM)
# --------------------------------------------------------------------------- #

def canonical_policy(trajectory_input: dict) -> list[dict]:
    """The oracle-optimal tool chain: parse once, then the full per-alert chain. Drives the
    arm to CORRECT+GROUNDED verdicts by construction (it collects the same evidence the
    graph does), so keyless CI still exercises the whole arm."""
    decisions: list[dict] = [{"tool": "parse_manifest", "alert_id": None}]
    for a in trajectory_input["alerts"]:
        aid = a["alert_id"]
        for tool in (
            "osv_query_package", "resolve_published_versions", "check_version_affected",
            "compute_minimal_fix", "crosscheck_second_source",
        ):
            decisions.append({"tool": tool, "alert_id": aid})
    return decisions


def lazy_policy(trajectory_input: dict) -> list[dict]:
    """A deliberately worse chain: skips the deps.dev cross-check. The arm still emits a
    valid, fully scoreable trajectory (source_agreement falls back to single_source, the
    minimal-fix claim loses its deps.dev grounding) — graceful degradation, never a crash."""
    return [d for d in canonical_policy(trajectory_input)
            if d["tool"] != "crosscheck_second_source"]


# --------------------------------------------------------------------------- #
# the live arm: a real ReAct policy over DeepSeek (house rule 9)
# --------------------------------------------------------------------------- #

class LLMReactPolicy:
    """ONE ReAct loop over DeepSeek: given the tools and the observations so far, pick the
    NEXT single tool call (or `__done__`). No planner, no supervisor. Requires LLM_API_KEY —
    used only in D9's ablation run, never in keyless CI. `model_route` records the model id
    in the trajectory."""

    def __init__(self, model_route: str):
        self.model_route = model_route

    def next(self, observation: dict) -> dict | None:
        from langchain_openai import ChatOpenAI

        from depguard.llm_meter import METER

        client = ChatOpenAI(
            model=os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
            base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
            api_key=os.environ["LLM_API_KEY"],
            temperature=0,
        )
        resp = client.invoke(self._prompt(observation))
        METER.record_call(resp)
        return self._parse(resp.content, observation)

    def _prompt(self, obs: dict) -> str:
        return (
            "You are DepGuard's single triage agent. For EACH alert, decide whether the "
            "pinned version is actually affected and the minimal safe upgrade, by calling "
            "tools ONE at a time. Emit ONLY a JSON object for the NEXT tool call: "
            '{"tool": <name>, "alert_id": <id or null>}. Tools: '
            + ", ".join(_TOOL_TO_ACTION) + ". Call parse_manifest once (alert_id=null); for "
            "each alert retrieve the advisory before checking containment, resolve versions "
            "before computing the minimal fix. When every alert is fully assessed, emit "
            '{"tool": "__done__", "alert_id": null}.\nAlerts: '
            + json.dumps(obs["alerts"]) + "\nHistory: " + json.dumps(obs["history"])
        )

    def _parse(self, raw: str, obs: dict) -> dict | None:
        try:
            start, end = raw.index("{"), raw.rindex("}") + 1
            decision = json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError):
            return None  # unparseable ⇒ stop (verdicts from whatever was gathered)
        tool = decision.get("tool")
        if tool == "__done__" or tool not in _TOOL_TO_ACTION:
            return None
        aid = decision.get("alert_id")
        valid = {a["alert_id"] for a in obs["alerts"]} | {None}
        return {"tool": tool, "alert_id": aid if aid in valid else None}


# --------------------------------------------------------------------------- #
# executor
# --------------------------------------------------------------------------- #

class _Executor:
    """Executes one tool decision at a time, accumulating per-alert state and emitting the
    trajectory's plan steps / tool calls / evidence, then verdicts on `finish()`."""

    def __init__(self, builder: TrajectoryBuilder, snapshot, alerts, trajectory_input):
        self.builder = builder
        self.snapshot = snapshot
        self.snapshot_id = snapshot.snapshot_id
        self.alerts = alerts  # alert_id -> alert
        self.input = trajectory_input
        self.per_alert: dict[str, dict] = {}
        self._order: list[str] = []  # alert_ids in first-seen order (stable verdicts)
        self._history: list[dict] = []

    def observation(self) -> dict:
        return {
            "alerts": self.input["alerts"],
            "tools": list(_TOOL_TO_ACTION),
            "history": self._history,
        }

    def step(self, decision: dict) -> None:
        tool = decision["tool"]
        aid = decision.get("alert_id")
        action = _TOOL_TO_ACTION[tool]
        agent = "retriever" if action in _RETRIEVER_ACTIONS else "tool_worker"
        if tool == "parse_manifest":
            self._parse_manifest(agent, action)
        elif aid not in self.alerts:
            # A per-alert tool needs a valid alert_id, but a real LLM sometimes emits a
            # null/unknown one. Treat it as a wasted no-op step (recorded in history so the
            # ReAct loop can course-correct) — NEVER crash the whole run on one bad decision.
            self._history.append({"tool": tool, "alert_id": aid,
                                  "result": {"ignored": "missing or unknown alert_id"}})
            return
        else:
            if aid not in self._order:
                self._order.append(aid)
            {
                "osv_query_package": self._retrieve,
                "resolve_published_versions": self._resolve,
                "check_version_affected": self._check,
                "compute_minimal_fix": self._minfix,
                "crosscheck_second_source": self._crosscheck,
            }[tool](agent, action, aid)
        pa = self.per_alert.get(aid, {})
        self._history.append({"tool": tool, "alert_id": aid, "result": self._summary(tool, pa)})

    def finish(self) -> None:
        for aid in self._order:
            pa = self.per_alert.get(aid, {})
            if pa.get("record") is None:
                # nothing retrieved ⇒ no evidence ⇒ cannot emit (§3.3 evidence minItems 1)
                self.builder.add_plan_step("emit_verdict", aid, _RATIONALE["emit_verdict"],
                                           status="skipped")
                continue
            self.builder.add_verdict(assemble_verdict(aid, pa))
            self.builder.add_plan_step("emit_verdict", aid, _RATIONALE["emit_verdict"],
                                       status="executed", produced_verdict_for=aid)

    # -- per-decision handlers -------------------------------------------- #
    def _parse_manifest(self, agent, action):
        manifest = self.input["manifest"]
        ecosystem = manifest[0]["ecosystem"] if manifest else "npm"
        text = self._synthesize_manifest(ecosystem, manifest)
        fname = "package.json" if ecosystem == "npm" else "requirements.json"
        result = parse_manifest(ecosystem, fname, text, corpus_snapshot_id=self.snapshot_id)
        self.builder.add_tool_call(
            agent=agent, tool_name="parse_manifest",
            arguments={"ecosystem": ecosystem, "manifest_filename": fname,
                       "manifest_text": text},
            result=result, source="local",
        )
        self.builder.add_plan_step(action, None, _RATIONALE[action], status="executed")

    def _retrieve(self, agent, action, aid):
        a = self.alerts[aid]
        result = osv_query_package(a["ecosystem"], a["name"], a["pinned_version"],
                                   snapshot=self.snapshot)
        tc_id = self.builder.add_tool_call(
            agent=agent, tool_name="osv_query_package",
            arguments={"ecosystem": a["ecosystem"], "name": a["name"],
                       "version": a["pinned_version"]},
            result=result, source="osv",
        )
        advisories = result["data"]["advisories"] if result["ok"] else []
        record = _find_record(advisories, a["advisory_id"])
        pa = self.per_alert.setdefault(aid, {})
        pa["record"] = record
        if record is not None:
            pa["osv_evidence_id"] = self.builder.add_evidence(
                osv_evidence_row(a, record, tc_id, self.snapshot_id))
        self.builder.add_plan_step(action, aid, _RATIONALE[action], status="executed")

    def _resolve(self, agent, action, aid):
        a = self.alerts[aid]
        result = resolve_published_versions(a["ecosystem"], a["name"], snapshot=self.snapshot)
        self.builder.add_tool_call(
            agent=agent, tool_name="resolve_published_versions",
            arguments={"ecosystem": a["ecosystem"], "name": a["name"]},
            result=result, source="deps.dev",
        )
        versions = result["data"]["versions"] if result["ok"] else []
        self.per_alert.setdefault(aid, {})["versions"] = versions
        self.builder.add_plan_step(action, aid, _RATIONALE[action], status="executed")

    def _check(self, agent, action, aid):
        a = self.alerts[aid]
        pa = self.per_alert.setdefault(aid, {})
        record = pa.get("record")
        if record is None:  # ordering error: no advisory to check against
            self.builder.add_plan_step(action, aid, _RATIONALE[action], status="skipped")
            return
        result = check_version_affected(a["ecosystem"], a["name"], a["pinned_version"],
                                        record, corpus_snapshot_id=self.snapshot_id)
        self.builder.add_tool_call(
            agent=agent, tool_name="check_version_affected",
            arguments={"ecosystem": a["ecosystem"], "name": a["name"],
                       "version": a["pinned_version"], "osv_record": {"id": record["id"]}},
            result=result, source="local",
        )
        data = result["data"] if result["ok"] else {}
        pa["contained"] = bool(data.get("contained"))
        pa["withdrawn_ts"] = data.get("withdrawn_timestamp")
        self.builder.add_plan_step(action, aid, _RATIONALE[action], status="executed")

    def _minfix(self, agent, action, aid):
        a = self.alerts[aid]
        pa = self.per_alert.setdefault(aid, {})
        record = pa.get("record")
        if record is None:
            self.builder.add_plan_step(action, aid, _RATIONALE[action], status="skipped")
            return
        result = compute_minimal_fix(a["ecosystem"], a["name"], a["pinned_version"], record,
                                     pa.get("versions", []), corpus_snapshot_id=self.snapshot_id)
        self.builder.add_tool_call(
            agent=agent, tool_name="compute_minimal_fix",
            arguments={"ecosystem": a["ecosystem"], "name": a["name"],
                       "current_version": a["pinned_version"],
                       "osv_record": {"id": record["id"]}},
            result=result, source="local",
        )
        pa["minimal_fixed"] = result["data"]["minimal_fixed_version"] if result["ok"] else None
        self.builder.add_plan_step(action, aid, _RATIONALE[action], status="executed")

    def _crosscheck(self, agent, action, aid):
        a = self.alerts[aid]
        pa = self.per_alert.setdefault(aid, {})
        record = pa.get("record")
        if record is None:
            self.builder.add_plan_step(action, aid, _RATIONALE[action], status="skipped")
            return
        osv_verdict = {"contained": pa.get("contained", False),
                       "advisory_id": record["id"], "aliases": record.get("aliases", [])}
        result = crosscheck_second_source(a["ecosystem"], a["name"], a["pinned_version"],
                                          osv_verdict, snapshot=self.snapshot)
        tc_id = self.builder.add_tool_call(
            agent=agent, tool_name="crosscheck_second_source",
            arguments={"ecosystem": a["ecosystem"], "name": a["name"],
                       "version": a["pinned_version"],
                       "osv_verdict": {"advisory_id": record["id"]}},
            result=result, source="deps.dev",
        )
        if result["ok"]:
            d = result["data"]
            pa["agreement"] = d["agreement"]
            pa["dd_evidence_id"] = self.builder.add_evidence(
                depsdev_evidence_row(a, record, d, pa.get("versions", []), tc_id,
                                     self.snapshot_id))
        self.builder.add_plan_step(action, aid, _RATIONALE[action], status="executed")

    # -- helpers ----------------------------------------------------------- #
    def _synthesize_manifest(self, ecosystem, manifest) -> str:
        entries = [m for m in manifest if m["ecosystem"] == ecosystem]
        if ecosystem == "npm":
            return json.dumps({"dependencies":
                               {m["name"]: m["pinned_version"] for m in entries}})
        return json.dumps({m["name"]: m["pinned_version"] for m in entries})

    @staticmethod
    def _summary(tool, pa) -> dict:
        """A compact observation the ReAct policy sees after each call (§ReAct feedback)."""
        if tool == "osv_query_package":
            return {"advisory_found": pa.get("record") is not None}
        if tool == "resolve_published_versions":
            return {"n_versions": len(pa.get("versions", []))}
        if tool == "check_version_affected":
            return {"contained": pa.get("contained"),
                    "withdrawn": pa.get("withdrawn_ts") is not None}
        if tool == "compute_minimal_fix":
            return {"minimal_fixed": pa.get("minimal_fixed")}
        if tool == "crosscheck_second_source":
            return {"agreement": pa.get("agreement")}
        return {}


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def run_single_agent(
    trajectory_input: dict,
    snapshot: Snapshot,
    *,
    policy=None,
    model_route: str | None = None,
    max_steps: int = 64,
) -> dict:
    """Run the single-agent arm over one triage input; return a validated §3 Trajectory.

    `policy` is a batch callable (scripted) OR an interactive object with `.next()`
    (`LLMReactPolicy`, the default when None). Interactive policies are driven in a real
    observe→act loop capped at `max_steps`."""
    if policy is None:
        route = model_route or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
        policy = LLMReactPolicy(route)
    else:
        route = model_route or getattr(policy, "model_route", None) or "single_agent/scripted-policy"

    builder = TrajectoryBuilder(
        system_variant=ARM, model_route=route,
        corpus_snapshot_id=snapshot.snapshot_id, trajectory_input=trajectory_input,
    )
    ex = _Executor(
        builder, snapshot,
        {a["alert_id"]: a for a in trajectory_input["alerts"]}, trajectory_input,
    )
    if hasattr(policy, "next"):  # interactive ReAct loop
        for _ in range(max_steps):
            decision = policy.next(ex.observation())
            if not decision or decision.get("tool") in (None, "__done__"):
                break
            ex.step(decision)
    else:  # batch scripted policy
        for decision in policy(trajectory_input):
            ex.step(decision)
    ex.finish()
    return builder.build()
