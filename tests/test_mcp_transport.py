"""The MCP server runs on both `mcp` majors, and over HTTP as well as stdio.

TWO CHANGES, ONE FILE.

**mcp 2.x compatibility.** The SDK renamed `FastMCP` to `MCPServer` in 2.0, and because
`pyproject.toml` carried an unbounded `mcp>=1.2`, a fresh install silently resolved to 2.x
and `depguard-mcp` stopped importing at all. CI caught it; the emergency fix was a `<2` pin.
The real fix is to work on both, since the API surface DepGuard uses — the `tool()`
decorator and `run(transport=...)` — is identical across the two majors. The pin is now
bounded at the next major (`<3`) rather than removed, because "no upper bound" is what
caused the outage.

**Streamable HTTP.** v0.1 declared stdio-only and put HTTP in the backlog. Both majors ship
`run_streamable_http_async` and `streamable_http_app`, so the transport is a CLI flag, not
a rewrite.

NOTE ON THE NO-NETWORK INVARIANT. Serving over HTTP is *inbound*; it does not give the tool
layer outbound network access, and `tests/test_external_tools.py` still greps this module
for outbound-network references. That test matches on `http://` and `https://` literals, so
this module deliberately never spells a URL out — host and port stay separate values.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
REGISTRY = json.loads(
    (REPO / "schemas" / "plan_action_tool_map.json").read_text())["tool_names"]


def test_server_imports_on_the_installed_mcp_major():
    """The regression that broke CI: this module must import regardless of which major
    is resolved."""
    from depguard import mcp_server

    assert mcp_server.mcp is not None
    assert mcp_server.MCP_MAJOR in (1, 2)


def test_compat_alias_resolves_to_the_right_class():
    from depguard.mcp_server import MCP_MAJOR, MCPServerClass

    name = MCPServerClass.__name__
    assert name == ("FastMCP" if MCP_MAJOR == 1 else "MCPServer"), name


def test_all_six_registry_tools_are_registered_whichever_major():
    """Guards the migration itself: a rename that quietly dropped a decorator would
    still import cleanly."""
    from depguard import mcp_server

    for name in REGISTRY:
        assert hasattr(mcp_server, name), f"{name} missing from the server module"


def test_transport_choices_are_declared():
    from depguard.mcp_server import TRANSPORTS

    assert TRANSPORTS[0] == "stdio", "stdio must remain the default-first choice"
    assert "streamable-http" in TRANSPORTS


def test_http_app_is_constructible():
    """`streamable_http_app()` is what a real deployment mounts. If the SDK changes its
    name again, this fails here rather than in production."""
    from depguard.mcp_server import mcp

    assert hasattr(mcp, "streamable_http_app")
    assert callable(mcp.streamable_http_app)


def test_main_rejects_an_unknown_transport():
    proc = subprocess.run(
        [sys.executable, "-m", "depguard.mcp_server", "--transport", "carrier-pigeon"],
        capture_output=True, text=True, cwd=str(REPO), timeout=60,
    )
    assert proc.returncode != 0
    assert "carrier-pigeon" in (proc.stderr + proc.stdout)


def test_main_help_documents_both_transports():
    proc = subprocess.run(
        [sys.executable, "-m", "depguard.mcp_server", "--help"],
        capture_output=True, text=True, cwd=str(REPO), timeout=60,
    )
    assert proc.returncode == 0
    out = proc.stdout
    assert "stdio" in out and "streamable-http" in out


def test_module_spells_no_outbound_url():
    """The no-network invariant is enforced by a grep in test_external_tools.py, and
    mcp_server.py is NOT on its allowlist. Serving over HTTP must not introduce a URL
    literal into this module."""
    text = (REPO / "depguard" / "mcp_server.py").read_text()
    for needle in ("http://", "https://", "urllib.request", "requests.get", "socket."):
        assert needle not in text, f"{needle!r} appeared in mcp_server.py"


@pytest.mark.parametrize("flag", ["--host", "--port", "--path"])
def test_http_options_exist(flag):
    proc = subprocess.run(
        [sys.executable, "-m", "depguard.mcp_server", "--help"],
        capture_output=True, text=True, cwd=str(REPO), timeout=60,
    )
    assert flag in proc.stdout
