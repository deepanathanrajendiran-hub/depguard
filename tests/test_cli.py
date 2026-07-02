"""D11/D12 — the keyless triage CLI (never-cut demo path). Verifies it triages a manifest
file against the frozen corpus and prints AFFECTED / not-affected / WITHDRAWN verdicts, and
that it falls back to a canned example when the manifest hits nothing."""

from __future__ import annotations

import json

from depguard.cli import main


def test_cli_triages_npm_and_prints_verdicts(tmp_path, capsys):
    mf = tmp_path / "package.json"
    mf.write_text(json.dumps({"dependencies": {"lodash": "4.17.20", "minimist": "1.2.0"}}))
    rc = main([str(mf)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "corpus depguard-corpus-" in out
    assert "AFFECTED" in out          # lodash 4.17.20
    assert "4.17.21" in out           # its minimal fix
    assert "WITHDRAWN" in out         # minimist advisory
    assert "actually affected" in out


def test_cli_falls_back_when_nothing_hits(tmp_path, capsys):
    mf = tmp_path / "package.json"
    mf.write_text(json.dumps({"dependencies": {"totally-made-up-pkg": "1.0.0"}}))
    rc = main([str(mf)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[fallback]" in out
    assert "AFFECTED" in out  # the canned example still shows real verdicts


def test_cli_missing_file_errors():
    assert main(["/no/such/manifest.json"]) == 2
