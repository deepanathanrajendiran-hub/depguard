"""D6 — OTel GenAI spans mirror the Trajectory 1:1 (DECISIONS.md §3.1).

Runs the graph with an in-memory span exporter and asserts every tool_call's
span_id / parent_span_id equals an exported span id, and every execute_tool span
carries the literal gen_ai.* attributes.
"""

import sys
from pathlib import Path

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from depguard.graph import run_graph  # noqa: E402
from depguard.otel import export_trajectory_spans  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402
from golden.seeds import SEED_INPUTS  # noqa: E402


def _run_and_export(seed="tp_lodash"):
    traj = run_graph(SEED_INPUTS[seed], Snapshot(), system_variant="deterministic_script")
    exporter = InMemorySpanExporter()
    export_trajectory_spans(traj, exporter=exporter)
    return traj, exporter.get_finished_spans()


def _hex_span(span):
    return format(span.get_span_context().span_id, "016x")


def _hex_trace(span):
    return format(span.get_span_context().trace_id, "032x")


def test_tool_call_span_ids_mirror_exported_spans_one_to_one():
    traj, spans = _run_and_export()
    tool_spans = [s for s in spans if s.name != "depguard.triage"]
    root_spans = [s for s in spans if s.name == "depguard.triage"]
    assert len(root_spans) == 1
    assert len(tool_spans) == len(traj["tool_calls"])

    exported_ids = {_hex_span(s) for s in tool_spans}
    for tc in traj["tool_calls"]:
        assert tc["span_id"] in exported_ids, f"{tc['tool_name']} span_id not exported"

    # root span id + trace id match the trajectory's otel block 1:1
    assert _hex_span(root_spans[0]) == traj["otel"]["root_span_id"]
    assert _hex_trace(root_spans[0]) == traj["otel"]["trace_id"]


def test_tool_call_parent_is_the_root_span():
    traj, spans = _run_and_export()
    for tc in traj["tool_calls"]:
        assert tc["parent_span_id"] == traj["otel"]["root_span_id"]
    for s in spans:
        if s.name != "depguard.triage":
            assert s.parent is not None
            assert format(s.parent.span_id, "016x") == traj["otel"]["root_span_id"]


def test_execute_tool_spans_carry_literal_gen_ai_attributes():
    traj, spans = _run_and_export()
    by_span_id = {_hex_span(s): s for s in spans if s.name != "depguard.triage"}
    for tc in traj["tool_calls"]:
        span = by_span_id[tc["span_id"]]
        attrs = dict(span.attributes)
        assert attrs["gen_ai.operation.name"] == "execute_tool"
        assert attrs["gen_ai.agent.name"] == tc["agent"]
        assert attrs["gen_ai.tool.name"] == tc["tool_name"]
        assert attrs["gen_ai.tool.call.id"] == tc["tool_call_id"]
        assert attrs["gen_ai.conversation.id"] == traj["trajectory_id"]


def test_export_is_noop_without_langfuse_keys(monkeypatch):
    """No exporter + no Langfuse keys ⇒ export completes without error (no-op)."""
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    traj = run_graph(SEED_INPUTS["seed_01"], Snapshot(), system_variant="deterministic_script")
    provider = export_trajectory_spans(traj)  # exporter=None -> configure_langfuse -> None
    assert provider is not None  # ran, exported nothing
