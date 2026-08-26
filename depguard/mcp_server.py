"""DepGuard's six triage tools, published as a typed MCP server (DECISIONS.md §0.1).

Any stock MCP client (Claude Code, Claude Desktop, …) installs it and gets the same six
tools the agents use, returning the same `{ok,data,error}` envelope verbatim. Tool NAMES are
exactly the §0.1 registry (`schemas/plan_action_tool_map.json`), enforced by test against
that file. Nothing is printed to stdout at import or run time except the MCP protocol itself
(stdout is the stdio channel).

TRANSPORTS (v0.3). stdio remains the default; Streamable HTTP — deferred in v0.1 — is now a
flag, because both `mcp` majors ship it and it is a transport choice rather than a rewrite.
Serving over HTTP is *inbound* and does not give the tool layer outbound network access:
the server still reads ONLY the frozen `corpus/` (a package-relative Snapshot), with no
network and no API key. `tests/test_external_tools.py` greps this module for outbound
references and it is NOT on that allowlist, so this file deliberately never spells a URL
out — host and port stay separate values.

SDK COMPATIBILITY. `mcp` 2.0 renamed `FastMCP` to `MCPServer`. Because `pyproject.toml`
carried an unbounded `mcp>=1.2`, a fresh install silently resolved to 2.x and this module
stopped importing at all — CI caught it, and the emergency fix was a `<2` pin. The real fix
is below: the API surface DepGuard uses (the `tool()` decorator, `run(transport=...)`) is
identical across both majors, so one alias covers them. The pin is now bounded at the next
major rather than removed, since "no upper bound" is precisely what caused the outage.
"""

from __future__ import annotations

import argparse
from functools import lru_cache

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as MCPServerClass

    MCP_MAJOR = 2
except ModuleNotFoundError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServerClass

    MCP_MAJOR = 1

from depguard.snapshot import Snapshot
from depguard.tools import external as _external
from depguard.tools import pure as _pure

#: stdio first — it is the default and the only transport a stock desktop client needs.
TRANSPORTS = ("stdio", "sse", "streamable-http")

mcp = MCPServerClass("depguard")


@lru_cache(maxsize=1)
def _snapshot() -> Snapshot:
    """One cached handle on the frozen corpus (package-relative; cwd-independent)."""
    return Snapshot()


@mcp.tool()
def parse_manifest(ecosystem: str, manifest_filename: str, manifest_text: str) -> dict:
    """§2.4 tool 1 — parse a dependency manifest (npm package.json / PyPI flat JSON) into
    pinned (ecosystem, name, version) rows. Returns the {ok,data,error} envelope."""
    snap = _snapshot()
    return _pure.parse_manifest(
        ecosystem, manifest_filename, manifest_text, corpus_snapshot_id=snap.snapshot_id)


@mcp.tool()
def osv_query_package(ecosystem: str, name: str, version: str | None = None) -> dict:
    """§2.4 tool 2 — the frozen-corpus OSV advisories affecting (ecosystem, name). Absence
    is ok/empty, not an error. `version` is accepted for /v1/query parity."""
    return _external.osv_query_package(ecosystem, name, version, snapshot=_snapshot())


@mcp.tool()
def check_version_affected(ecosystem: str, name: str, version: str, osv_record: dict) -> dict:
    """§2.4 tool 3 — RAW range containment of `version` against one OSV `osv_record` (pass a
    record from osv_query_package). Surfaces withdrawn_timestamp verbatim; the withdrawn
    override is a verdict-layer rule, NOT applied here."""
    snap = _snapshot()
    return _pure.check_version_affected(
        ecosystem, name, version, osv_record, corpus_snapshot_id=snap.snapshot_id)


@mcp.tool()
def resolve_published_versions(ecosystem: str, name: str) -> dict:
    """§2.4 tool 4 — published-version list from the frozen deps.dev extract, ascending."""
    return _external.resolve_published_versions(ecosystem, name, snapshot=_snapshot())


@mcp.tool()
def compute_minimal_fix(
    ecosystem: str, name: str, current_version: str,
    osv_record: dict, published_versions: list[str],
) -> dict:
    """§2.4 tool 5 — smallest PUBLISHED version that clears `osv_record` (withdrawn
    short-circuits to null). Pass published_versions from resolve_published_versions."""
    snap = _snapshot()
    return _pure.compute_minimal_fix(
        ecosystem, name, current_version, osv_record, published_versions,
        corpus_snapshot_id=snap.snapshot_id)


@mcp.tool()
def crosscheck_second_source(
    ecosystem: str, name: str, version: str, osv_verdict: dict,
) -> dict:
    """§2.4 tool 6 — reconcile OSV's RAW containment against deps.dev per-version advisory
    keys (agree / disagree / single_source). `osv_verdict` carries
    {contained, advisory_id, aliases} from check_version_affected."""
    return _external.crosscheck_second_source(
        ecosystem, name, version, osv_verdict, snapshot=_snapshot())


def main(argv: list[str] | None = None) -> None:
    """Console entry point (`depguard-mcp`). Defaults to stdio."""
    parser = argparse.ArgumentParser(
        prog="depguard-mcp",
        description="DepGuard's six triage tools over MCP. Reads only the frozen corpus: "
                    "no outbound network, no API key.",
    )
    parser.add_argument("--transport", choices=TRANSPORTS, default="stdio",
                        help="stdio (default) or streamable-http / sse for a served "
                             "deployment")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address for the served transports (default: loopback)")
    parser.add_argument("--port", type=int, default=8000,
                        help="bind port for the served transports (default: 8000)")
    parser.add_argument("--path", default="/mcp",
                        help="URL path for streamable-http (default: /mcp)")
    args = parser.parse_args(argv)

    if args.transport == "stdio":
        mcp.run()
        return
    # Bind settings live on the server object in both majors; pass them there rather than
    # through run(), whose keyword surface differs between 1.x and 2.x.
    for attr, value in (("host", args.host), ("port", args.port),
                        ("streamable_http_path", args.path)):
        settings = getattr(mcp, "settings", None)
        if settings is not None and hasattr(settings, attr):
            setattr(settings, attr, value)
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
