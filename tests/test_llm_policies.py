"""De-risk the never-run LLM code paths WITHOUT a key: the response PARSERS are the fragile
part (the network call is a thin client.invoke). We feed canned model outputs and assert the
planner/ReAct parsers accept valid plans, reject out-of-enum actions, and coerce bad ids.
"""

from __future__ import annotations

from depguard.arms.single_agent import LLMReactPolicy
from depguard.graph import LLMPlanner

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
