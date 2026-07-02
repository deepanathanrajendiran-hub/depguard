"""Canonical `corpus_snapshot_id` computation + `SNAPSHOT.lock` access (§0.5).

ONE source of truth for the id formula, imported by BOTH the freeze script
(`scripts/freeze_micro.py`, which stamps the id into `SNAPSHOT.lock`) and the
corpus test (`tests/test_corpus.py`, which recomputes it from the on-disk bytes)
and the snapshot loader — so the stored id and any recomputation cannot drift.

v0.1 form (DECISIONS.md editorial note 3 — NO `all.zip` operand in the micro-corpus):

    corpus_snapshot_id = "depguard-corpus-<capture_date>-" + sha256(
        b"".join(sorted osv record file bytes)
        ‖ b"".join(sorted deps.dev extract file bytes)
        ‖ curation_ruleset_version.encode("utf-8")
    ).hexdigest()[:12]

Bytes are the EXACT on-disk file contents; ordering is by POSIX relative path so
freeze-time and test-time agree. The id is a strict one-way input to `SNAPSHOT.lock`
(the lock references the id; the id never hashes the lock — §0.5, cycle broken).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sorted_file_bytes(root: Path) -> bytes:
    """Concatenate every *.json under `root`, ordered by POSIX relative path."""
    if not root.is_dir():
        return b""
    files = sorted(root.rglob("*.json"), key=lambda p: p.relative_to(root).as_posix())
    return b"".join(p.read_bytes() for p in files)


def compute_snapshot_id(
    corpus_dir: str | Path, capture_date: str, curation_ruleset_version: str
) -> str:
    """Recompute `corpus_snapshot_id` from the frozen bytes on disk (§0.5)."""
    corpus_dir = Path(corpus_dir)
    osv_bytes = _sorted_file_bytes(corpus_dir / "osv")
    extract_bytes = _sorted_file_bytes(corpus_dir / "depsdev_extract")
    digest = hashlib.sha256(
        osv_bytes + extract_bytes + curation_ruleset_version.encode("utf-8")
    ).hexdigest()[:12]
    return f"depguard-corpus-{capture_date}-{digest}"


def load_snapshot_lock(corpus_dir: str | Path) -> dict:
    """Parse `corpus/SNAPSHOT.lock` (JSON)."""
    return json.loads((Path(corpus_dir) / "SNAPSHOT.lock").read_text())
