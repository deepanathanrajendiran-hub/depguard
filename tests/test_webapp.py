"""D11 — the demo webapp (docs/HANDOFF_D8-D14.md §D11).

Covers the honest staging (frozen-snapshot label, no live scanner), the SSE triage stream
producing real verdicts, and the coverage-aware fallback to a canned lockfile when the paste
fails to parse OR hits nothing in the corpus (an empty table is the real demo-death).
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from depguard.snapshot import Snapshot
from depguard.webapp import CANNED, app, triage_events

client = TestClient(app)
SNAP = Snapshot()


def _events(resp_text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in resp_text.split("\n\n")
            if line.startswith("data: ")]


# ------------------------------- unit: triage_events ---------------------- #

def test_triage_events_real_verdicts_on_corpus_hits():
    events = list(triage_events("npm", CANNED["npm"], SNAP))
    meta = events[0]
    assert meta["type"] == "meta" and meta["fallback"] is False
    verdicts = {e["alert_id"]: e for e in events if e["type"] == "verdict"}
    # lodash 4.17.20 IS affected (fix 4.17.21); minimist's advisory is withdrawn
    aff = [v for v in verdicts.values() if v["affected"]]
    withdrawn = [v for v in verdicts.values() if v["withdrawn"]]
    assert aff, "expected at least one AFFECTED verdict (lodash/axios)"
    assert withdrawn, "expected the withdrawn minimist advisory to be non-actionable"
    assert any(v["minimal_fixed_version"] == "4.17.21" for v in aff)


def test_triage_events_evidence_is_cited():
    events = list(triage_events("npm", CANNED["npm"], SNAP))
    v = next(e for e in events if e["type"] == "verdict")
    assert v["evidence"] is not None
    assert v["evidence"]["advisory_id"]
    assert v["evidence"]["range_type"] in ("SEMVER", "ECOSYSTEM", "GIT")


# ------------------------------- routes ----------------------------------- #

def test_index_states_it_is_not_a_live_scanner():
    r = client.get("/")
    assert r.status_code == 200
    assert "not" in r.text.lower() and "live scanner" in r.text.lower()
    assert "frozen" in r.text.lower()


def test_healthz_reports_snapshot():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["corpus_snapshot_id"].startswith("depguard-corpus-")


def test_triage_stream_npm_corpus_hits():
    r = client.post("/triage", json={"ecosystem": "npm", "manifest_text": CANNED["npm"]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _events(r.text)
    assert events[0]["fallback"] is False
    assert any(e["type"] == "verdict" and e["affected"] for e in events)
    assert events[-1]["type"] == "done"


def test_triage_fallback_on_zero_corpus_hits():
    """A manifest that parses but hits nothing falls back to the canned lockfile (never an
    empty table) and still streams real verdicts."""
    mf = json.dumps({"dependencies": {"not-a-real-package-xyz": "1.0.0"}})
    r = client.post("/triage", json={"ecosystem": "npm", "manifest_text": mf})
    events = _events(r.text)
    assert events[0]["fallback"] is True
    assert any(e["type"] == "verdict" for e in events)


def test_triage_fallback_on_unparseable_manifest():
    r = client.post("/triage", json={"ecosystem": "npm", "manifest_text": "}{not json"})
    events = _events(r.text)
    assert events[0]["fallback"] is True
    assert "parse" in events[0]["note"].lower()
    assert any(e["type"] == "verdict" for e in events)
