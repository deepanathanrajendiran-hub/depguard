# DepGuard MCP server

DepGuard's six dependency-triage tools, published as a typed [Model Context
Protocol](https://modelcontextprotocol.io) server. Any stock MCP client (Claude Code,
Claude Desktop, …) can install it and call the exact same tools the agents use — each
returning the same `{ok, data, error}` envelope.

- **Transport:** stdio only. (Streamable HTTP is deliberately out of scope for v0.1 — see
  `docs/DEPGUARD_BACKLOG.md`.)
- **Data:** the frozen `corpus/` snapshot only. **No network, no API key.** Verdicts are
  reproducible against `corpus_snapshot_id = depguard-corpus-2026-07-01-c6f3471a2245`.

## The six tools

Names are exactly the §0.1 registry (`schemas/plan_action_tool_map.json`):

| tool | purpose |
|---|---|
| `parse_manifest` | parse an npm `package.json` / PyPI flat-JSON into pinned rows |
| `osv_query_package` | OSV advisories affecting `(ecosystem, name)` from the corpus |
| `check_version_affected` | RAW semver-range containment of a version against one OSV record |
| `resolve_published_versions` | published-version list from the frozen deps.dev extract |
| `compute_minimal_fix` | smallest published version that clears the advisory |
| `crosscheck_second_source` | reconcile OSV containment vs deps.dev (agree/disagree/single_source) |

A typical chain: `osv_query_package` → pick a record → `check_version_affected` →
`resolve_published_versions` → `compute_minimal_fix` → `crosscheck_second_source`.

## Install & run

From the repo (editable), or once published to PyPI:

```bash
pip install -e .          # or: pip install depguard
depguard-mcp              # starts the stdio server (waits for a client on stdin/stdout)
```

`depguard-mcp` is the console entry point (`depguard.mcp_server:main`). Equivalently:

```bash
python -m depguard.mcp_server
```

## Client configuration

### Claude Code

```bash
claude mcp add depguard -- depguard-mcp
```

or, without installing the console script:

```bash
claude mcp add depguard -- python -m depguard.mcp_server
```

### Claude Desktop / any client with a JSON config

Add to the client's MCP servers config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "depguard": {
      "command": "depguard-mcp"
    }
  }
}
```

If the console script isn't on `PATH`, use the absolute interpreter + module form:

```json
{
  "mcpServers": {
    "depguard": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "depguard.mcp_server"]
    }
  }
}
```

## Example call

`check_version_affected` on the headline false positive — lodash `4.17.21` is the *fixed*
release, so it is **not** contained by `GHSA-35jh-r3h4-6jhm`:

```jsonc
// arguments
{ "ecosystem": "npm", "name": "lodash", "version": "4.17.21",
  "osv_record": { /* a record from osv_query_package */ } }
// result (structured content)
{ "ok": true, "data": { "contained": false, "withdrawn_timestamp": null, ... }, "error": null }
```

Errors are typed envelopes, never exceptions — e.g. an unsupported ecosystem returns
`{ "ok": false, "data": null, "error": { "code": "BAD_INPUT", "retryable": false, ... } }`.
