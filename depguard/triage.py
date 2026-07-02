"""The demo triage core (docs/HANDOFF_D8-D14.md §D11), transport-agnostic and LLM-free.

Both the web demo (`depguard/webapp.py`, SSE) and the CLI (`depguard/cli.py`) drive this — so
the CLI works with NO web framework installed (house rule 13: if the build slips, the web page
is cut but the CLI stays). Alerts are SYNTHESIZED by querying the frozen corpus for advisories
affecting each pasted dependency (not a live scanner); the triage runs the deterministic
`script_arm`. Coverage-aware fallback (review HIGH-2): a manifest that fails to parse OR hits
nothing in the corpus falls back to a canned famous lockfile — never an empty table.
"""

from __future__ import annotations

import os

from depguard.arms.script_arm import run_script_arm
from depguard.otel import export_trajectory_spans
from depguard.tools.external import osv_query_package
from depguard.tools.pure import parse_manifest

# Canned lockfiles whose dependencies are known to hit the frozen corpus, so the fallback
# always shows real, verifiable verdicts (npm: affected + withdrawn + fp; PyPI likewise).
CANNED = {
    "npm": '{"dependencies": {"lodash": "4.17.20", "minimist": "1.2.0", '
           '"axios": "1.3.6", "cross-spawn": "7.0.5"}}',
    "PyPI": '{"django": "2.2", "requests": "2.6.0", "pillow": "8.0.0", "redis": "4.3.4"}',
}


def _synthesize(ecosystem: str, manifest_text: str, snapshot) -> dict | None:
    """Parse a manifest and synthesize one alert per (dependency, corpus advisory). Returns a
    §3 trajectory input {manifest, alerts}, or None if the manifest does not parse."""
    fname = "package.json" if ecosystem == "npm" else "requirements.json"
    parsed = parse_manifest(ecosystem, fname, manifest_text,
                            corpus_snapshot_id=snapshot.snapshot_id)
    if not parsed["ok"]:
        return None
    manifest, alerts = [], []
    for i, dep in enumerate(parsed["data"]["dependencies"]):
        eco, name, ver = dep["ecosystem"], dep["name"], dep["version"]
        manifest.append({"ecosystem": eco, "name": name, "pinned_version": ver, "purl": None})
        q = osv_query_package(eco, name, ver, snapshot=snapshot)
        if not q["ok"]:
            continue
        for adv in q["data"]["advisories"]:
            alerts.append({"alert_id": f"alert-{i}-{adv['id']}", "ecosystem": eco,
                           "name": name, "pinned_version": ver,
                           "advisory_id": adv["id"], "source": "scanner"})
    return {"manifest": manifest, "alerts": alerts}


def _build_input(ecosystem: str, manifest_text: str, snapshot):
    """(input, fallback, note). Falls back to a canned lockfile when the paste fails to parse
    OR yields zero corpus hits — never an empty table."""
    inp = _synthesize(ecosystem, manifest_text, snapshot)
    if inp is None:
        return (_synthesize(ecosystem, CANNED[ecosystem], snapshot), True,
                "Could not parse the manifest — showing a canned example lockfile instead.")
    if not inp["alerts"]:
        return (_synthesize(ecosystem, CANNED[ecosystem], snapshot), True,
                "None of those dependencies are in the frozen 2026-07 corpus — showing a "
                "canned example so you can see real verdicts.")
    return inp, False, ("Alerts derived from the frozen 2026-07 snapshot so every verdict is "
                        "verifiable — this is NOT a live scanner.")


def _osv_evidence(trajectory: dict) -> dict | None:
    for ev in trajectory["evidence"]:
        if ev["source"] == "osv":
            return {"advisory_id": ev["advisory_id"], "range_type": ev["range_type"],
                    "range_events": ev["range_events"], "withdrawn": ev["withdrawn"],
                    "references": [r["url"] for r in ev.get("references", [])][:2]}
    return None


def triage_events(ecosystem: str, manifest_text: str, snapshot):
    """Sync generator of triage event dicts (transport-agnostic). Web wraps each as one SSE
    frame; the CLI prints each. Env-gated Langfuse export (§D6) fires per trajectory when
    LANGFUSE_* keys are set."""
    inp, fallback, note = _build_input(ecosystem, manifest_text, snapshot)
    yield {"type": "meta", "snapshot_id": snapshot.snapshot_id, "ecosystem": ecosystem,
           "n_alerts": len(inp["alerts"]), "fallback": fallback, "note": note}
    n_affected = 0
    for alert in inp["alerts"]:
        traj = run_script_arm({"manifest": inp["manifest"], "alerts": [alert]}, snapshot)
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            export_trajectory_spans(traj)  # each triaged trajectory → one Langfuse trace
        yield {"type": "alert", "alert_id": alert["alert_id"], "name": alert["name"],
               "version": alert["pinned_version"], "advisory_id": alert["advisory_id"]}
        for step in traj["plan"]:
            if step["status"] == "executed" and step["action"] != "plan":
                yield {"type": "step", "alert_id": alert["alert_id"], "action": step["action"]}
        v = traj["verdicts"][0] if traj["verdicts"] else None
        if v is not None:
            n_affected += 1 if v["affected"] else 0
            yield {"type": "verdict", "alert_id": v["alert_id"], "affected": v["affected"],
                   "minimal_fixed_version": v["minimal_fixed_version"],
                   "withdrawn": v["withdrawn"], "source_agreement": v["source_agreement"],
                   "evidence": _osv_evidence(traj)}
    yield {"type": "done", "n_alerts": len(inp["alerts"]), "n_affected": n_affected}
