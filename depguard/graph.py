"""The DepGuard graph (DECISIONS.md §Architecture, spec §4): LangGraph
supervisor → planner → retriever → tool_worker → verifier, emitting a schema-valid
§3 Trajectory.

Two arms of the three-arm ablation share this executor, differing ONLY in the
planner:

- `deterministic_script` — a rule-based planner emits the canonical §0.2 plan (NO
  LLM). This is the ablation's deterministic arm AND the arm the seed/golden tests
  run, so the graph is mechanically verified in plain CI with no API key.
- `multi_agent` — the planner is an LLM (DeepSeek via the OpenAI-format client,
  house rule 9), the ONLY LLM node in v0.1; its plan is validated against the §0.2
  enum (out-of-enum actions rejected/retried) and then executed identically.

The executor FOLLOWS the plan (a worse plan ⇒ missing tool calls ⇒ worse verdicts),
so the ablation measures something real. Every pure/external tool IS the oracle, so
the deterministic arm's predicted verdicts equal the oracle gold by construction.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from depguard.agreement import agreement_state, observe_from_extract
from depguard.oracle import record_containment, select_entries
from depguard.snapshot import Snapshot
from depguard.tools.external import (
    crosscheck_second_source,
    osv_query_package,
    resolve_published_versions,
)
from depguard.tools.pure import (
    check_version_affected,
    compute_minimal_fix,
    minimal_fix_gold,
    parse_manifest,
)
from depguard.trajectory import TrajectoryBuilder, gold_ref_for

# action -> executing agent (§0.2 / §3 toolCall.agent enum)
_RETRIEVER_ACTIONS = {"parse_manifest", "retrieve_advisory", "resolve_versions"}
_WORKER_ACTIONS = {"check_containment", "compute_minimal_fixed", "cross_check_source"}
_LEGAL_ACTIONS = {
    "plan", "parse_manifest", "retrieve_advisory", "resolve_versions",
    "check_containment", "compute_minimal_fixed", "cross_check_source", "emit_verdict",
}

_SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"


# --------------------------------------------------------------------------- #
# planners
# --------------------------------------------------------------------------- #

def deterministic_plan(manifest: list[dict], alerts: list[dict]) -> list[dict]:
    """The canonical §0.2 plan: control steps, then each alert's full chain."""
    plan = [
        {"action": "plan", "alert_id": None, "rationale": "decompose the triage task"},
        {"action": "parse_manifest", "alert_id": None,
         "rationale": "parse the dependency manifest"},
    ]
    for a in alerts:
        aid = a["alert_id"]
        plan += [
            {"action": "retrieve_advisory", "alert_id": aid,
             "rationale": f"fetch OSV advisories for {a['name']}"},
            {"action": "resolve_versions", "alert_id": aid,
             "rationale": f"list published versions of {a['name']}"},
            {"action": "check_containment", "alert_id": aid,
             "rationale": "is the pinned version in the affected range?"},
            {"action": "compute_minimal_fixed", "alert_id": aid,
             "rationale": "smallest published safe upgrade"},
            {"action": "cross_check_source", "alert_id": aid,
             "rationale": "reconcile against deps.dev"},
            {"action": "emit_verdict", "alert_id": aid,
             "rationale": "emit the reconciled verdict"},
        ]
    return plan


class LLMPlanner:
    """The `multi_agent` arm's planner — DeepSeek via the OpenAI-format client
    (house rule 9). Emits plan-as-data; actions outside the §0.2 enum are rejected
    and one retry is attempted before falling back to the canonical plan."""

    def __init__(self, model_route: str):
        self.model_route = model_route
        self.fell_back = False  # set True if BOTH LLM attempts fail and we use the canonical plan

    def __call__(self, manifest: list[dict], alerts: list[dict]) -> list[dict]:
        from langchain_openai import ChatOpenAI

        from depguard.llm_meter import METER

        client = ChatOpenAI(
            model=os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
            base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
            api_key=os.environ["LLM_API_KEY"],
            temperature=0,
        )
        prompt = self._prompt(manifest, alerts)
        for _ in range(2):
            resp = client.invoke(prompt)
            METER.record_call(resp)
            plan = self._parse(resp.content, alerts)
            if plan is not None:
                return plan
        # BOTH attempts failed — running the deterministic plan here would make this arm
        # silently identical to the script arm, so mark it LOUDLY (meter + model_route).
        self.fell_back = True
        METER.record_fallback()
        return deterministic_plan(manifest, alerts)

    def _prompt(self, manifest, alerts) -> str:
        return (
            "You are DepGuard's planner. Emit ONLY a JSON array of steps; each step "
            '{"action","alert_id","rationale"}. Legal actions (use EXACTLY these): '
            + ", ".join(sorted(_LEGAL_ACTIONS)) + ". "
            "Start with a `plan` then `parse_manifest` (both alert_id=null). For EACH "
            "alert emit retrieve_advisory, resolve_versions, check_containment, "
            "compute_minimal_fixed, cross_check_source, emit_verdict with that "
            "alert's alert_id.\nAlerts: " + json.dumps(alerts)
        )

    def _parse(self, raw: str, alerts) -> list[dict] | None:
        try:
            start, end = raw.index("["), raw.rindex("]") + 1
            steps = json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError):
            return None
        valid_ids = {a["alert_id"] for a in alerts} | {None}
        out = []
        for s in steps:
            if s.get("action") not in _LEGAL_ACTIONS:
                return None  # out-of-enum ⇒ reject the whole plan, retry
            aid = s.get("alert_id")
            out.append({
                "action": s["action"],
                "alert_id": aid if aid in valid_ids else None,
                "rationale": str(s.get("rationale", "")),
            })
        return out or None


# --------------------------------------------------------------------------- #
# the pipeline (executor)
# --------------------------------------------------------------------------- #

class Pipeline:
    def __init__(self, trajectory_input, snapshot, *, system_variant, model_route, planner):
        self.input = trajectory_input
        self.snapshot = snapshot
        self.planner = planner
        self.builder = TrajectoryBuilder(
            system_variant=system_variant,
            model_route=model_route,
            corpus_snapshot_id=snapshot.snapshot_id,
            trajectory_input=trajectory_input,
        )
        self.alerts = {a["alert_id"]: a for a in trajectory_input["alerts"]}
        self.retrieved: dict[tuple[str, str], dict] = {}  # (eco,name) -> data
        self.per_alert: dict[str, dict] = {}  # alert_id -> intermediate results

    # -- planner ----------------------------------------------------------- #
    def run_planner(self):
        for step in self.planner(self.input["manifest"], self.input["alerts"]):
            self.builder.add_plan_step(
                step["action"], step["alert_id"], step["rationale"], status="planned"
            )
        # the `plan` control step is the planner's own act
        for i, step in enumerate(self.builder._plan):
            if step["action"] == "plan":
                self.builder.mark_executed(i)

    # -- retriever --------------------------------------------------------- #
    def run_retriever(self):
        for i, step in enumerate(self.builder._plan):
            if step["action"] not in _RETRIEVER_ACTIONS:
                continue
            if step["action"] == "parse_manifest":
                self._exec_parse_manifest(i)
            elif step["action"] == "retrieve_advisory":
                self._exec_retrieve(i, step["alert_id"])
            elif step["action"] == "resolve_versions":
                self._exec_resolve(i, step["alert_id"])

    def _exec_parse_manifest(self, step_index):
        manifest = self.input["manifest"]
        ecosystem = manifest[0]["ecosystem"] if manifest else "npm"
        text = self._synthesize_manifest(ecosystem, manifest)
        fname = "package.json" if ecosystem == "npm" else "requirements.json"
        result = parse_manifest(
            ecosystem, fname, text, corpus_snapshot_id=self.snapshot.snapshot_id
        )
        self.builder.add_tool_call(
            agent="retriever", tool_name="parse_manifest",
            arguments={"ecosystem": ecosystem, "manifest_filename": fname,
                       "manifest_text": text},
            result=result, source="local",
        )
        self.builder.mark_executed(step_index)

    def _exec_retrieve(self, step_index, alert_id):
        a = self.alerts[alert_id]
        eco, name = a["ecosystem"], a["name"]
        result = osv_query_package(eco, name, a["pinned_version"], snapshot=self.snapshot)
        tc_id = self.builder.add_tool_call(
            agent="retriever", tool_name="osv_query_package",
            arguments={"ecosystem": eco, "name": name, "version": a["pinned_version"]},
            result=result, source="osv",
        )
        advisories = result["data"]["advisories"] if result["ok"] else []
        record = _find_record(advisories, a["advisory_id"])
        self.retrieved.setdefault((eco, name), {})["advisories"] = advisories
        pa = self.per_alert.setdefault(alert_id, {})
        pa["record"] = record
        if record is not None:
            pa["osv_evidence_id"] = self._add_osv_evidence(alert_id, record, tc_id)
        self.builder.mark_executed(step_index)

    def _exec_resolve(self, step_index, alert_id):
        a = self.alerts[alert_id]
        eco, name = a["ecosystem"], a["name"]
        result = resolve_published_versions(eco, name, snapshot=self.snapshot)
        self.builder.add_tool_call(
            agent="retriever", tool_name="resolve_published_versions",
            arguments={"ecosystem": eco, "name": name},
            result=result, source="deps.dev",
        )
        versions = result["data"]["versions"] if result["ok"] else []
        self.retrieved.setdefault((eco, name), {})["versions"] = versions
        self.per_alert.setdefault(alert_id, {})["versions"] = versions
        self.builder.mark_executed(step_index)

    # -- tool_worker ------------------------------------------------------- #
    def run_tool_worker(self):
        for i, step in enumerate(self.builder._plan):
            if step["action"] not in _WORKER_ACTIONS:
                continue
            aid = step["alert_id"]
            if step["action"] == "check_containment":
                self._exec_check(i, aid)
            elif step["action"] == "compute_minimal_fixed":
                self._exec_minfix(i, aid)
            elif step["action"] == "cross_check_source":
                self._exec_crosscheck(i, aid)

    def _exec_check(self, step_index, alert_id):
        a = self.alerts[alert_id]
        pa = self.per_alert.setdefault(alert_id, {})
        record = pa.get("record")
        if record is None:
            self.builder._plan[step_index]["status"] = "skipped"
            return
        result = check_version_affected(
            a["ecosystem"], a["name"], a["pinned_version"], record,
            corpus_snapshot_id=self.snapshot.snapshot_id,
        )
        self.builder.add_tool_call(
            agent="tool_worker", tool_name="check_version_affected",
            arguments={"ecosystem": a["ecosystem"], "name": a["name"],
                       "version": a["pinned_version"], "osv_record": {"id": record["id"]}},
            result=result, source="local",
        )
        data = result["data"] if result["ok"] else {}
        pa["contained"] = bool(data.get("contained"))
        pa["withdrawn_ts"] = data.get("withdrawn_timestamp")
        self.builder.mark_executed(step_index)

    def _exec_minfix(self, step_index, alert_id):
        a = self.alerts[alert_id]
        pa = self.per_alert.setdefault(alert_id, {})
        record = pa.get("record")
        versions = pa.get("versions", [])
        if record is None:
            self.builder._plan[step_index]["status"] = "skipped"
            return
        result = compute_minimal_fix(
            a["ecosystem"], a["name"], a["pinned_version"], record, versions,
            corpus_snapshot_id=self.snapshot.snapshot_id,
        )
        self.builder.add_tool_call(
            agent="tool_worker", tool_name="compute_minimal_fix",
            arguments={"ecosystem": a["ecosystem"], "name": a["name"],
                       "current_version": a["pinned_version"],
                       "osv_record": {"id": record["id"]}},
            result=result, source="local",
        )
        pa["minimal_fixed"] = result["data"]["minimal_fixed_version"] if result["ok"] else None
        self.builder.mark_executed(step_index)

    def _exec_crosscheck(self, step_index, alert_id):
        a = self.alerts[alert_id]
        pa = self.per_alert.setdefault(alert_id, {})
        record = pa.get("record")
        if record is None:
            self.builder._plan[step_index]["status"] = "skipped"
            return
        osv_verdict = {
            "contained": pa.get("contained", False),
            "advisory_id": record["id"],
            "aliases": record.get("aliases", []),
        }
        result = crosscheck_second_source(
            a["ecosystem"], a["name"], a["pinned_version"], osv_verdict,
            snapshot=self.snapshot,
        )
        tc_id = self.builder.add_tool_call(
            agent="tool_worker", tool_name="crosscheck_second_source",
            arguments={"ecosystem": a["ecosystem"], "name": a["name"],
                       "version": a["pinned_version"],
                       "osv_verdict": {"advisory_id": record["id"]}},
            result=result, source="deps.dev",
        )
        if result["ok"]:
            d = result["data"]
            pa["agreement"] = d["agreement"]
            pa["dd_evidence_id"] = self._add_depsdev_evidence(alert_id, record, d, pa, tc_id)
        self.builder.mark_executed(step_index)

    # -- verifier ---------------------------------------------------------- #
    def run_verifier(self):
        for i, step in enumerate(self.builder._plan):
            if step["action"] != "emit_verdict":
                continue
            aid = step["alert_id"]
            if self.per_alert.get(aid, {}).get("record") is None:
                # retrieval failed / advisory absent → nothing to verdict (a branch);
                # skip rather than emit an evidence-less verdict (§3.3 minItems 1).
                self.builder._plan[i]["status"] = "skipped"
                continue
            self._emit_verdict(aid)
            self.builder.mark_executed(i, produced_verdict_for=aid)

    def _emit_verdict(self, alert_id):
        self.builder.add_verdict(assemble_verdict(alert_id, self.per_alert.get(alert_id, {})))

    # -- evidence helpers (thin wrappers over the shared module-level builders) -- #
    def _add_osv_evidence(self, alert_id, record, tool_call_id) -> str:
        row = osv_evidence_row(
            self.alerts[alert_id], record, tool_call_id, self.snapshot.snapshot_id
        )
        return self.builder.add_evidence(row)

    def _add_depsdev_evidence(self, alert_id, record, crosscheck_data, pa, tool_call_id) -> str:
        row = depsdev_evidence_row(
            self.alerts[alert_id], record, crosscheck_data,
            pa.get("versions", []), tool_call_id, self.snapshot.snapshot_id,
        )
        return self.builder.add_evidence(row)

    def _synthesize_manifest(self, ecosystem, manifest) -> str:
        entries = [m for m in manifest if m["ecosystem"] == ecosystem]
        if ecosystem == "npm":
            return json.dumps({"dependencies": {m["name"]: m["pinned_version"] for m in entries}})
        return json.dumps({m["name"]: m["pinned_version"] for m in entries})

    def result(self) -> dict:
        return self.builder.build()


def _find_record(advisories, advisory_id):
    for rec in advisories:
        if rec.get("id") == advisory_id or advisory_id in rec.get("aliases", []):
            return rec
    return None


def _matched_entry(record, eco, name, version):
    """The affected entry that DECIDES containment for `version` (the witness), so the
    Evidence row cites the entry that actually produced the verdict — critical for
    multi-`affected[]` records where a later entry is the one containing the version.
    Falls back to the first E_A entry when none contains (a not-contained verdict)."""
    entries = select_entries(record, eco, name)
    for e in entries:
        try:
            if record_containment(dict(record, affected=[e]), eco, name, version).contained:
                return e
        except Exception:  # noqa: BLE001 — undecidable entry, keep looking
            continue
    return entries[0] if entries else None


def _osv_evidence_fields(record, eco, name, version):
    entry = _matched_entry(record, eco, name, version)
    if entry is None:
        return "ECOSYSTEM", [], None
    semver = [r for r in entry.get("ranges") or [] if r.get("type") == "SEMVER"]
    if semver:
        return "SEMVER", list(semver[0].get("events", [])), (entry.get("versions") or None)
    ranges = entry.get("ranges") or []
    if ranges:
        return ranges[0].get("type", "ECOSYSTEM"), list(ranges[0].get("events", [])), \
            (entry.get("versions") or None)
    return "ECOSYSTEM", [], (entry.get("versions") or None)


# --------------------------------------------------------------------------- #
# LangGraph wiring
# --------------------------------------------------------------------------- #

class _State(TypedDict):
    pipe: Any


def _compile():
    sg = StateGraph(_State)
    sg.add_node("planner", lambda s: (s["pipe"].run_planner(), s)[1])
    sg.add_node("retriever", lambda s: (s["pipe"].run_retriever(), s)[1])
    sg.add_node("tool_worker", lambda s: (s["pipe"].run_tool_worker(), s)[1])
    sg.add_node("verifier", lambda s: (s["pipe"].run_verifier(), s)[1])
    sg.add_edge(START, "planner")
    sg.add_edge("planner", "retriever")
    sg.add_edge("retriever", "tool_worker")
    sg.add_edge("tool_worker", "verifier")
    sg.add_edge("verifier", END)
    return sg.compile()


_APP = _compile()


def run_graph(
    trajectory_input: dict,
    snapshot: Snapshot,
    *,
    system_variant: str = "deterministic_script",
    model_route: str | None = None,
    planner: Callable | None = None,
) -> dict:
    """Run the whole graph offline on the frozen corpus; return a validated §3
    Trajectory. Default arm = `deterministic_script` (no LLM)."""
    if planner is None:
        if system_variant == "multi_agent":
            planner = LLMPlanner(model_route or os.environ.get("LLM_MODEL", "deepseek-v4-flash"))
        else:
            planner = deterministic_plan
    if model_route is None:
        model_route = (
            os.environ.get("LLM_MODEL", "deepseek-v4-flash")
            if system_variant == "multi_agent" else "deterministic_script/none"
        )
    pipe = Pipeline(
        trajectory_input, snapshot,
        system_variant=system_variant, model_route=model_route, planner=planner,
    )
    _APP.invoke({"pipe": pipe})
    # If the LLM planner fell back to the canonical plan, stamp it into model_route so the
    # trajectory itself records that this run was NOT genuinely LLM-planned (D9 review).
    if getattr(planner, "fell_back", False):
        pipe.builder.model_route = f"{model_route} (planner-fallback→deterministic)"
    return pipe.result()


# --------------------------------------------------------------------------- #
# gold sidecar (§4.5) — labeled by the SAME oracle the tools call
# --------------------------------------------------------------------------- #

def _scored_args_registry() -> dict:
    return json.loads((_SCHEMAS / "tool_key_args.json").read_text())


def gold_verdict(alert: dict, snapshot: Snapshot) -> dict:
    """The oracle's gold Verdict for one alert (same functions the tools use)."""
    eco, name, version = alert["ecosystem"], alert["name"], alert["pinned_version"]
    q = osv_query_package(eco, name, version, snapshot=snapshot)
    advisories = q["data"]["advisories"] if q["ok"] else []
    record = _find_record(advisories, alert["advisory_id"])
    if record is None:
        return {"alert_id": alert["alert_id"], "affected": False,
                "minimal_fixed_version": None, "withdrawn": False, "cvss3_score": None,
                "evidence_ids": [], "source_agreement": "single_source",
                "reconciliation_note": ""}
    withdrawn = record.get("withdrawn") is not None
    contained = record_containment(record, eco, name, version).contained
    affected = contained and not withdrawn
    versions = resolve_published_versions(eco, name, snapshot=snapshot)["data"]["versions"]
    minimal_fixed = None
    if not withdrawn:
        minimal_fixed, _reason, _c = minimal_fix_gold(eco, name, version, record, versions)
    extract = snapshot.read_extract(eco, name)
    alias_set = frozenset({record["id"], *record.get("aliases", [])})
    agreement = agreement_state(contained, alias_set, observe_from_extract(extract, version))
    return {
        "alert_id": alert["alert_id"],
        "affected": affected,
        "minimal_fixed_version": minimal_fixed,
        "withdrawn": withdrawn,
        "cvss3_score": None,
        "evidence_ids": [f"ev-osv-{alert['alert_id']}", f"ev-dd-{alert['alert_id']}"],
        "source_agreement": agreement,
        "reconciliation_note": "" if agreement != "disagree"
        else "OSV and deps.dev disagree on this version",
    }


def build_gold(trajectory_input: dict, snapshot: Snapshot) -> dict:
    """Gold sidecar (§4.5): canonical plan actions + scored tool calls + oracle
    verdicts. Labeled by running the oracle, never by hand."""
    manifest, alerts = trajectory_input["manifest"], trajectory_input["alerts"]
    plan = deterministic_plan(manifest, alerts)
    reg = _scored_args_registry()
    action_to_tool = {
        "parse_manifest": "parse_manifest",
        "retrieve_advisory": "osv_query_package",
        "resolve_versions": "resolve_published_versions",
        "check_containment": "check_version_affected",
        "compute_minimal_fixed": "compute_minimal_fix",
        "cross_check_source": "crosscheck_second_source",
    }
    ecosystem = manifest[0]["ecosystem"] if manifest else "npm"
    gold_tool_calls = []
    for step in plan:
        tool = action_to_tool.get(step["action"])
        if tool is None:
            continue
        alert = next((a for a in alerts if a["alert_id"] == step["alert_id"]), None)
        gold_tool_calls.append({
            "tool_name": tool,
            "scored_args": _gold_scored_args(tool, reg[tool], alert, ecosystem),
        })
    return {
        "gold_ref": gold_ref_for(trajectory_input),
        "gold_plan_actions": [s["action"] for s in plan],
        # gold_plan carries alert_id per step — required for the alert-grouped
        # plan-adherence metric (§4.1.3); gold_plan_actions alone cannot group.
        "gold_plan": [{"action": s["action"], "alert_id": s["alert_id"]} for s in plan],
        "gold_tool_calls": gold_tool_calls,
        "gold_verdicts": [gold_verdict(a, snapshot) for a in alerts],
    }


def _gold_scored_args(tool, keys, alert, ecosystem) -> dict:
    out = {}
    for key in keys:
        if key == "ecosystem":
            out[key] = alert["ecosystem"] if alert else ecosystem
        elif key == "manifest_filename":
            out[key] = "package.json" if ecosystem == "npm" else "requirements.json"
        elif key == "name":
            out[key] = alert["name"] if alert else None
        elif key in ("version", "current_version"):
            out[key] = alert["pinned_version"] if alert else None
        elif key in ("osv_record.id", "osv_verdict.advisory_id"):
            out[key] = alert["advisory_id"] if alert else None
    return out

def osv_evidence_row(alert: dict, record: dict, tool_call_id: str, snapshot_id: str) -> dict:
    """The §3.2 OSV Evidence row for one alert — shared by the graph Pipeline AND the
    single-agent arm so both cite identical, verifier-groundable evidence (one builder,
    no drift). Cites the affected entry that WITNESSES containment (`_matched_entry`)."""
    eco, name, version = alert["ecosystem"], alert["name"], alert["pinned_version"]
    range_type, range_events, enumerated = _osv_evidence_fields(record, eco, name, version)
    prov = record.get("_provenance", {})
    return {
        "evidence_id": f"ev-osv-{alert['alert_id']}",
        "alert_id": alert["alert_id"],
        "tool_call_id": tool_call_id,
        "source": "osv",
        "advisory_id": record["id"],
        "withdrawn": record.get("withdrawn"),
        "affected_package": {"ecosystem": eco, "name": name},
        "range_type": range_type,
        "range_events": range_events,
        "enumerated_versions": enumerated,
        "references": [
            {"type": r.get("type", "WEB"), "url": r["url"]}
            for r in record.get("references", []) if r.get("url")
        ],
        "license": prov.get("license", "CC0-1.0"),
        "attribution_url": prov.get("source_url"),
        "corpus_snapshot_id": snapshot_id,
    }


def depsdev_evidence_row(alert: dict, record: dict, crosscheck_data: dict,
                         versions: list[str], tool_call_id: str, snapshot_id: str) -> dict:
    """The §3.2 deps.dev Evidence row — shared builder (see `osv_evidence_row`)."""
    meta = crosscheck_data.get("source_meta", {})
    return {
        "evidence_id": f"ev-dd-{alert['alert_id']}",
        "alert_id": alert["alert_id"],
        "tool_call_id": tool_call_id,
        "source": "deps.dev",
        "advisory_id": record["id"],
        "checked_version": alert["pinned_version"],
        "second_source_advisory_keys": crosscheck_data.get("second_source_advisory_keys", []),
        "per_version_affected_bool": crosscheck_data.get("per_version_affected_bool", False),
        "published_versions": versions,
        "license": "CC-BY-4.0",
        "attribution_url": meta.get("source_url") or "deps.dev (attribution unavailable)",
        "corpus_snapshot_id": snapshot_id,
    }


def assemble_verdict(alert_id: str, pa: dict) -> dict:
    """The §3.3 Verdict from one alert's accumulated tool results — the withdrawn override
    lives HERE (not in the tool). Shared by the Pipeline verifier node AND the single-agent
    arm so all three ablation arms emit verdicts by the identical rule."""
    contained = pa.get("contained", False)
    withdrawn = pa.get("withdrawn_ts") is not None
    affected = contained and not withdrawn
    minimal_fixed = None if withdrawn else pa.get("minimal_fixed")
    agreement = pa.get("agreement", "single_source")
    note = "" if agreement != "disagree" else "OSV and deps.dev disagree on this version"
    evidence_ids = [e for e in (pa.get("osv_evidence_id"), pa.get("dd_evidence_id")) if e]
    return {
        "alert_id": alert_id,
        "affected": affected,
        "minimal_fixed_version": minimal_fixed,
        "withdrawn": withdrawn,
        "cvss3_score": None,
        "evidence_ids": evidence_ids,
        "source_agreement": agreement,
        "reconciliation_note": note,
    }
