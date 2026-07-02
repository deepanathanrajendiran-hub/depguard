"""OpenTelemetry GenAI spans mirroring the Trajectory 1:1 (DECISIONS.md §3.1).

The Trajectory is the source of truth; spans are REPLAYED from a finished trajectory
so `tool_calls[].span_id` / `parent_span_id` equal the exported span ids exactly
(1:1). A deterministic `IdGenerator` seeded from the trajectory's own ids makes the
replay reproducible, so committed golden trajectories stay byte-stable while still
carrying REAL OTel span ids.

Span attributes are LITERAL OTel GenAI semconv (§3.1): `gen_ai.operation.name` (from
`schemas/plan_action_tool_map.json`), `gen_ai.agent.name`, `gen_ai.tool.name`,
`gen_ai.tool.call.id`, `gen_ai.conversation.id` = `trajectory_id`.

Langfuse export is opt-in: if `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are set,
traces go to the OTLP endpoint; otherwise export no-ops (tests don't care).
"""

from __future__ import annotations

import base64
import json
import os
from functools import lru_cache
from pathlib import Path

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.id_generator import IdGenerator

_SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"


@lru_cache(maxsize=1)
def _operation_names() -> dict:
    """tool_name -> gen_ai.operation.name, derived from plan_action_tool_map.json."""
    m = json.loads((_SCHEMAS / "plan_action_tool_map.json").read_text())
    out = {}
    for action in m["actions"].values():
        if action.get("tool_name"):
            out[action["tool_name"]] = action["gen_ai_operation_name"]
    return out


class _SeededIdGenerator(IdGenerator):
    """Yields the trajectory's own trace/span ids, in span-start order."""

    def __init__(self, trace_id_hex: str, span_ids_hex: list[str]):
        self._trace_id = int(trace_id_hex, 16)
        self._span_ids = [int(s, 16) for s in span_ids_hex]
        self._i = 0

    def generate_span_id(self) -> int:
        sid = self._span_ids[self._i % len(self._span_ids)]
        self._i += 1
        return sid

    def generate_trace_id(self) -> int:
        return self._trace_id


def export_trajectory_spans(trajectory: dict, *, exporter=None) -> TracerProvider:
    """Replay `trajectory` as OTel spans (root + one execute_tool span per tool call),
    exporting through `exporter` (an InMemorySpanExporter in tests, or the Langfuse
    OTLP exporter in production). Returns the provider (already flushed)."""
    span_order = [trajectory["otel"]["root_span_id"]] + [
        tc["span_id"] for tc in trajectory["tool_calls"]
    ]
    provider = TracerProvider(
        id_generator=_SeededIdGenerator(trajectory["otel"]["trace_id"], span_order)
    )
    if exporter is None:
        exporter = configure_langfuse_exporter()
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("depguard")
    ops = _operation_names()

    tid = trajectory["trajectory_id"]
    with tracer.start_as_current_span("depguard.triage") as root:
        root.set_attribute("gen_ai.conversation.id", tid)
        root.set_attribute("gen_ai.system", "depguard")
        root.set_attribute("depguard.system_variant", trajectory["system_variant"])
        for tc in trajectory["tool_calls"]:
            op = ops.get(tc["tool_name"], "execute_tool")
            with tracer.start_as_current_span(op) as span:
                span.set_attribute("gen_ai.operation.name", op)
                span.set_attribute("gen_ai.agent.name", tc["agent"])
                span.set_attribute("gen_ai.tool.name", tc["tool_name"])
                span.set_attribute("gen_ai.tool.call.id", tc["tool_call_id"])
                span.set_attribute("gen_ai.tool.type", tc["tool_type"])
                span.set_attribute("gen_ai.conversation.id", tid)
    provider.force_flush()
    return provider


def configure_langfuse_exporter():
    """An OTLP exporter to Langfuse if keys are set, else None (export no-ops)."""
    public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret = os.environ.get("LANGFUSE_SECRET_KEY")
    if not (public and secret):
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    auth = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return OTLPSpanExporter(
        endpoint=f"{host}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )
