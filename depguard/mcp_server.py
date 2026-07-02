"""DepGuard's six triage tools, published as a typed MCP server (DECISIONS.md §0.1). stdio transport ONLY — Streamable HTTP is BANNED in v0.1
(backlog). Any stock MCP client (Claude Code, Claude Desktop, …) installs it and gets the
same six tools the agents use, returning the same `{ok,data,error}` envelope verbatim.

The server reads ONLY the frozen `corpus/` (a package-relative Snapshot) — no network, no
API key. Tool NAMES are exactly the §0.1 registry (`schemas/plan_action_tool_map.json`),
which is enforced by test against that file. Nothing is printed to stdout at import or run
time except the MCP protocol itself (stdout is the stdio channel).
"""

from __future__ import annotations

from functools import lru_cache

from mcp.server.fastmcp import FastMCP

from depguard.snapshot import Snapshot
from depguard.tools import external as _external
from depguard.tools import pure as _pure

mcp = FastMCP("depguard")


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


def main() -> None:
    """Console entry point (`depguard-mcp`). stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
