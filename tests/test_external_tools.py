"""D4 — the three snapshot-backed EXTERNAL tools (DECISIONS.md §2.4 tools 2, 4, 6).

These read ONLY the frozen corpus/ and ARE the deterministic CI mocks — there is no
separate mock layer. Failures are envelope errors, never exceptions (§2.1). Tool 6's
agreement logic is the SAME `depguard.agreement.agreement_state` the §5 verifier uses
(shared-oracle principle) — asserted directly below.
"""

import json
from pathlib import Path

import pytest

from depguard.agreement import agreement_state, observe_from_extract
from depguard.comparators import VersionParseError, get_comparator
from depguard.corpus_snapshot import load_snapshot_lock
from depguard.snapshot import Snapshot
from depguard.tools.external import (
    crosscheck_second_source,
    osv_query_package,
    resolve_published_versions,
)

REPO = Path(__file__).parent.parent
CORPUS = REPO / "corpus"
FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "mini_corpus"
BROKEN = FIXTURES / "broken_json_corpus"

REAL_SNAP = load_snapshot_lock(CORPUS)["corpus_snapshot_id"]


def real():
    return Snapshot(CORPUS)


def assert_ok(env):
    assert env["ok"] is True, f"expected ok, got {env['error']}"
    assert env["error"] is None
    assert "source_meta" in env["data"]
    return env["data"]


def assert_err(env, code):
    assert env["ok"] is False, f"expected error, got {env['data']}"
    assert env["data"] is None
    assert env["error"]["code"] == code
    assert env["error"]["retryable"] is False
    return env["error"]


# ===================================================================== #
# Tool 2: osv_query_package
# ===================================================================== #

def test_osv_query_returns_corpus_advisories_for_package():
    data = assert_ok(osv_query_package("npm", "lodash", None, snapshot=real()))
    ids = {a["id"] for a in data["advisories"]}
    assert "GHSA-35jh-r3h4-6jhm" in ids
    assert data["corpus_snapshot_id"] == REAL_SNAP
    assert data["source_meta"]["corpus_snapshot_id"] == REAL_SNAP
    assert data["source_meta"]["source"] == "osv"


def test_osv_query_not_found_is_ok_empty_not_error():
    data = assert_ok(osv_query_package("npm", "no-such-package-xyz", None, snapshot=real()))
    assert data["advisories"] == []
    assert data["excluded"] == []


def test_osv_query_excludes_ecosystem_only_record():
    """Curation enforcement (§2.4 tool 2): an ECOSYSTEM-only-no-versions record for
    the package lands in excluded[{id,reason}], never in advisories."""
    data = assert_ok(osv_query_package("npm", "widget", None, snapshot=Snapshot(MINI)))
    adv_ids = {a["id"] for a in data["advisories"]}
    exc_ids = {e["id"] for e in data["excluded"]}
    assert adv_ids == {"GHSA-mini-tp-0001"}
    assert exc_ids == {"GHSA-mini-eco-0002"}
    assert data["excluded"][0]["reason"]  # a non-empty reason string


def test_osv_query_replay_is_byte_identical():
    a = osv_query_package("npm", "lodash", None, snapshot=real())
    b = osv_query_package("npm", "lodash", None, snapshot=real())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_osv_query_malformed_record_is_snapshot_malformed():
    assert_err(
        osv_query_package("npm", "anything", None, snapshot=Snapshot(BROKEN)),
        "SNAPSHOT_MALFORMED",
    )


def test_osv_query_missing_lock_is_snapshot_read_error(tmp_path):
    # a corpus dir with no SNAPSHOT.lock is structurally broken
    assert_err(
        osv_query_package("npm", "lodash", None, snapshot=Snapshot(tmp_path)),
        "SNAPSHOT_READ_ERROR",
    )


# ===================================================================== #
# Tool 4: resolve_published_versions
# ===================================================================== #

def test_resolve_returns_versions_sorted_ascending():
    data = assert_ok(resolve_published_versions("npm", "lodash", snapshot=real()))
    assert data["source_meta"]["source"] == "deps.dev"
    assert data["source_meta"]["license"] == "CC-BY-4.0"
    assert "4.17.20" in data["versions"] and "4.17.21" in data["versions"]
    cmp = get_comparator("npm")
    parseable = [v for v in data["versions"] if _parses(cmp, v)]
    assert parseable == cmp.sort(parseable), "published versions not ascending"
    assert data["default_version"] is not None


def test_resolve_not_found_is_ok_empty():
    data = assert_ok(resolve_published_versions("npm", "no-such-pkg", snapshot=real()))
    assert data["versions"] == []
    assert data["default_version"] is None


def test_resolve_malformed_extract_is_snapshot_malformed():
    assert_err(
        resolve_published_versions("PyPI", "gadget", snapshot=Snapshot(BROKEN)),
        "SNAPSHOT_MALFORMED",
    )


def test_resolve_grounds_minimal_fix_against_real_registry():
    """The load-bearing second signal (§1.3): resolve gives the real published list,
    so a lodash alert at 4.17.20 upgrades to the actually-published 4.17.21."""
    data = assert_ok(resolve_published_versions("npm", "lodash", snapshot=real()))
    assert "4.17.21" in data["versions"]


def _parses(cmp, v):
    try:
        cmp.key(v)
        return True
    except VersionParseError:
        return False


# ===================================================================== #
# Tool 6: crosscheck_second_source
# ===================================================================== #

def _verdict(contained, advisory_id, aliases):
    return {"contained": contained, "advisory_id": advisory_id, "aliases": aliases}


def test_crosscheck_agree_on_affected_version():
    v = _verdict(True, "GHSA-35jh-r3h4-6jhm", ["CVE-2021-23337"])
    data = assert_ok(crosscheck_second_source("npm", "lodash", "4.17.20", v, snapshot=real()))
    assert data["agreement"] == "agree"
    assert data["per_version_affected_bool"] is True
    assert "GHSA-35jh-r3h4-6jhm" in data["second_source_advisory_keys"]
    assert data["second_source"] == "deps.dev"
    assert data["source_meta"]["license"] == "CC-BY-4.0"
    assert data["corpus_snapshot_id"] == REAL_SNAP


def test_crosscheck_agree_on_fixed_version():
    # 4.17.21 is the fix — OSV says not contained, deps.dev attaches no key -> agree
    v = _verdict(False, "GHSA-35jh-r3h4-6jhm", ["CVE-2021-23337"])
    data = assert_ok(crosscheck_second_source("npm", "lodash", "4.17.21", v, snapshot=real()))
    assert data["agreement"] == "agree"
    assert data["per_version_affected_bool"] is False


def test_crosscheck_single_source_when_depsdev_lacks_advisory():
    # OSV-2022-1074 (pillow) has no aliases -> deps.dev never carries that key
    v = _verdict(True, "OSV-2022-1074", [])
    data = assert_ok(crosscheck_second_source("PyPI", "pillow", "9.1.0", v, snapshot=real()))
    assert data["agreement"] == "single_source"


def test_crosscheck_replay_is_byte_identical():
    v = _verdict(True, "GHSA-35jh-r3h4-6jhm", ["CVE-2021-23337"])
    a = crosscheck_second_source("npm", "lodash", "4.17.20", v, snapshot=real())
    b = crosscheck_second_source("npm", "lodash", "4.17.20", v, snapshot=real())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_crosscheck_shares_agreement_logic_with_verifier():
    """The tool's agreement MUST equal the shared agreement_state the verifier uses
    (same code, gold and inference) — this is the shared-oracle invariant."""
    snap = real()
    extract = json.loads((CORPUS / "depsdev_extract" / "npm" / "lodash.json").read_text())
    record = json.loads(
        (CORPUS / "osv" / "npm" / "GHSA-35jh-r3h4-6jhm.json").read_text()
    )
    alias_set = frozenset({record["id"], *record.get("aliases", [])})
    for version, contained in [("4.17.20", True), ("4.17.21", False)]:
        obs = observe_from_extract(extract, version)
        expected = agreement_state(contained, alias_set, obs)
        v = _verdict(contained, record["id"], record.get("aliases", []))
        data = assert_ok(crosscheck_second_source("npm", "lodash", version, v, snapshot=snap))
        assert data["agreement"] == expected


def test_crosscheck_malformed_extract_is_snapshot_malformed():
    v = _verdict(True, "X", [])
    assert_err(
        crosscheck_second_source("PyPI", "gadget", "1.0.0", v, snapshot=Snapshot(BROKEN)),
        "SNAPSHOT_MALFORMED",
    )


# ===================================================================== #
# No network in the tool layer (§1.4 / D4 acceptance)
# ===================================================================== #

def test_no_http_in_the_tool_and_data_layer():
    """The tool + corpus layer must never touch the network (§1.4). graph.py, otel.py and
    arms/single_agent.py are EXCLUDED: the `multi_agent` planner, the Langfuse OTLP
    exporter and the `single_agent` ReAct policy are the
    legitimate outbound LLM/telemetry integrations by design — all env-gated on
    LLM_API_KEY / an OTLP endpoint and never reached by the tool/corpus code."""
    import depguard
    root = Path(depguard.__file__).parent
    allowed_network = {"graph.py", "otel.py", "single_agent.py"}
    offenders = []
    for py in root.rglob("*.py"):
        if py.name in allowed_network:
            continue
        text = py.read_text()
        for needle in ("http://", "https://", "urllib.request", "requests.get", "socket."):
            if needle in text:
                offenders.append(f"{py.name}:{needle}")
    assert not offenders, f"network references in tool/data layer: {offenders}"
