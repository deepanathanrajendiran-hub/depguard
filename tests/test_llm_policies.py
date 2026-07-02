"""De-risk the never-run LLM code paths WITHOUT a key: the response PARSERS are the fragile
part (the network call is a thin client.invoke). We feed canned model outputs and assert the
planner/ReAct parsers accept valid plans, reject out-of-enum actions, and coerce bad ids.
"""

from __future__ import annotations

from depguard.arms.single_agent import LLMReactPolicy
from depguard.graph import LLMPlanner, deterministic_plan, run_graph
from depguard.llm_meter import LLMMeter
from depguard.snapshot import Snapshot
from golden.seeds import SEED_INPUTS

_OBS = {"alerts": [{"alert_id": "a1"}, {"alert_id": "a2"}], "tools": [], "history": []}


# --------------------------- single_agent ReAct parser --------------------- #

def test_react_parse_valid_decision():
    p = LLMReactPolicy("m")
    d = p._parse('{"tool": "osv_query_package", "alert_id": "a1"}', _OBS)
    assert d == {"tool": "osv_query_package", "alert_id": "a1"}


def test_react_parse_done_and_unknown_tool_stop():
    p = LLMReactPolicy("m")
    assert p._parse('{"tool": "__done__", "alert_id": null}', _OBS) is None
    assert p._parse('{"tool": "not_a_tool", "alert_id": "a1"}', _OBS) is None


def test_react_parse_coerces_unknown_alert_to_none():
    p = LLMReactPolicy("m")
    d = p._parse('reasoning... {"tool": "parse_manifest", "alert_id": "zzz"} done', _OBS)
    assert d == {"tool": "parse_manifest", "alert_id": None}


def test_react_parse_unparseable_stops():
    p = LLMReactPolicy("m")
    assert p._parse("no json here", _OBS) is None


# --------------------------- multi_agent planner parser -------------------- #

def test_planner_parse_valid_plan():
    alerts = [{"alert_id": "a1", "name": "x"}]
    raw = '[{"action":"plan","alert_id":null,"rationale":"r"},' \
          '{"action":"retrieve_advisory","alert_id":"a1","rationale":"r"}]'
    plan = LLMPlanner("m")._parse(raw, alerts)
    assert [s["action"] for s in plan] == ["plan", "retrieve_advisory"]
    assert plan[1]["alert_id"] == "a1"


def test_planner_parse_rejects_out_of_enum():
    alerts = [{"alert_id": "a1", "name": "x"}]
    raw = '[{"action":"HACK_THE_PLANET","alert_id":null,"rationale":"r"}]'
    assert LLMPlanner("m")._parse(raw, alerts) is None


def test_planner_parse_coerces_unknown_alert_to_none():
    alerts = [{"alert_id": "a1", "name": "x"}]
    raw = '[{"action":"emit_verdict","alert_id":"ghost","rationale":"r"}]'
    plan = LLMPlanner("m")._parse(raw, alerts)
    assert plan[0]["alert_id"] is None


# --------------------- fallback VISIBILITY (D9 review #2) ------------------- #

class _FellBackPlanner:
    """A planner that fell back to the canonical plan — mimics LLMPlanner after 2 failures."""
    fell_back = True

    def __call__(self, manifest, alerts):
        return deterministic_plan(manifest, alerts)


def test_planner_fallback_is_stamped_into_model_route():
    """A silent fallback would make multi_agent identical to the script for the WRONG
    reason; run_graph must record it in the trajectory's model_route."""
    traj = run_graph(SEED_INPUTS["seed_01"], Snapshot(), system_variant="multi_agent",
                     model_route="deepseek-v4-flash", planner=_FellBackPlanner())
    assert "planner-fallback" in traj["model_route"]


def test_no_fallback_leaves_model_route_clean():
    traj = run_graph(SEED_INPUTS["seed_01"], Snapshot(), system_variant="deterministic_script")
    assert "fallback" not in traj["model_route"]


def test_llmplanner_starts_not_fell_back():
    assert LLMPlanner("m").fell_back is False


# --------------------- token/fallback meter (D9 review #5) ----------------- #

class _FakeResp:
    def __init__(self, i, o):
        self.usage_metadata = {"input_tokens": i, "output_tokens": o}
        self.content = "x"


def test_meter_accumulates_tokens_cost_and_fallbacks():
    m = LLMMeter()
    m.record_call(_FakeResp(100, 40))
    m.record_call(_FakeResp(50, 10))
    m.record_fallback()
    s = m.snapshot()
    assert s["calls"] == 2
    assert s["prompt_tokens"] == 150 and s["completion_tokens"] == 50
    assert s["total_tokens"] == 200
    assert s["fallbacks"] == 1
    assert s["cost_usd"] > 0.0


def test_meter_reset_zeroes_everything():
    m = LLMMeter()
    m.record_call(_FakeResp(10, 10))
    m.reset()
    assert m.snapshot() == {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                            "total_tokens": 0, "cost_usd": 0.0, "fallbacks": 0}
