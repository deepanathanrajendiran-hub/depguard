"""`depguard-triage` — a keyless triage CLI over the frozen corpus (never-cut demo path).

Triages a manifest file against the frozen corpus and prints per-alert verdicts. No LLM, no
network, no API key, no web framework. Example:

    depguard-triage package.json
    depguard-triage --ecosystem PyPI requirements.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from depguard.snapshot import Snapshot
from depguard.triage import triage_events


def _format(event: dict) -> str | None:
    t = event["type"]
    if t == "meta":
        tag = " [fallback]" if event["fallback"] else ""
        return (f"# {event['note']}\n"
                f"# corpus {event['snapshot_id']} · {event['n_alerts']} alert(s){tag}")
    if t == "verdict":
        status = ("WITHDRAWN" if event["withdrawn"]
                  else "AFFECTED" if event["affected"] else "not affected")
        fix = f" → fix {event['minimal_fixed_version']}" if event["minimal_fixed_version"] else ""
        adv = event["evidence"]["advisory_id"] if event["evidence"] else "?"
        return f"{status:13} {event['alert_id']:34} {adv}{fix}"
    if t == "done":
        return f"# {event['n_affected']} of {event['n_alerts']} alert(s) actually affected"
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="depguard-triage",
        description="Triage a dependency manifest against the frozen DepGuard corpus.")
    p.add_argument("manifest", help="path to package.json (npm) or flat JSON (PyPI)")
    p.add_argument("--ecosystem", choices=["npm", "PyPI"], default="npm")
    args = p.parse_args(argv)

    try:
        text = Path(args.manifest).read_text()
    except OSError as exc:
        print(f"error: cannot read {args.manifest}: {exc}", file=sys.stderr)
        return 2

    for event in triage_events(args.ecosystem, text, Snapshot()):
        line = _format(event)
        if line is not None:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
