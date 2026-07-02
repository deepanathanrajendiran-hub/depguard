"""D10 — the MCP server. stdio ONLY.

Spawns the server as a real stdio subprocess with the official SDK client and asserts:
(1) list_tools returns EXACTLY the six §0.1 registry tool names, each with an input schema;
(2) a round-trip check_version_affected call returns the {ok,data,error} envelope verbatim.
No network — the server reads only the frozen corpus/. Async client is driven via
asyncio.run so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO = Path(__file__).resolve().parent.parent
REGISTRY = json.loads(
    (REPO / "schemas" / "plan_action_tool_map.json").read_text())["tool_names"]

_PARAMS = StdioServerParameters(
    command=sys.executable, args=["-m", "depguard.mcp_server"], cwd=str(REPO))


def _run(coro):
    return asyncio.run(coro)


def _envelope(call_result) -> dict:
    """Pull the {ok,data,error} envelope out of a CallToolResult (structured content if
    present, else the JSON text block)."""
    sc = getattr(call_result, "structuredContent", None)
    if isinstance(sc, dict) and {"ok", "data", "error"} <= set(sc):
        return sc
    if isinstance(sc, dict) and "result" in sc:  # FastMCP may wrap under 'result'
        return sc["result"]
    return json.loads(call_result.content[0].text)


async def _session(fn):
    async with stdio_client(_PARAMS) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            return await fn(session)


def test_lists_exactly_the_six_registry_tools():
    async def go(session):
        tools = await session.list_tools()
        return {t.name: t.inputSchema for t in tools.tools}

    schemas = _run(_session(go))
    assert sorted(schemas) == sorted(REGISTRY)
    for name in REGISTRY:
        assert schemas[name], f"{name} has no input schema"


def test_check_version_affected_roundtrip_envelope():
    async def go(session):
        q = await session.call_tool(
            "osv_query_package", {"ecosystem": "npm", "name": "lodash"})
        qenv = _envelope(q)
        rec = next(a for a in qenv["data"]["advisories"]
                   if a["id"] == "GHSA-35jh-r3h4-6jhm"
                   or "GHSA-35jh-r3h4-6jhm" in a.get("aliases", []))
        cva = await session.call_tool(
            "check_version_affected",
            {"ecosystem": "npm", "name": "lodash", "version": "4.17.21", "osv_record": rec})
        return qenv, _envelope(cva)

    qenv, env = _run(_session(go))
    assert qenv["ok"] is True
    # the envelope is returned verbatim (§2.1 shape)
    assert set(env.keys()) == {"ok", "data", "error"}
    assert env["ok"] is True and env["error"] is None
    # 4.17.21 is the FIXED release ⇒ not contained (the headline false positive)
    assert env["data"]["contained"] is False


def test_bad_input_is_a_typed_error_envelope_not_an_exception():
    async def go(session):
        r = await session.call_tool(
            "parse_manifest",
            {"ecosystem": "haskell", "manifest_filename": "x", "manifest_text": "{}"})
        return _envelope(r)

    env = _run(_session(go))
    assert env["ok"] is False
    assert env["error"]["code"] == "BAD_INPUT"
    assert env["error"]["retryable"] is False
