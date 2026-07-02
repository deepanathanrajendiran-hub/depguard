"""Frozen-corpus loader for the EXTERNAL tools (DECISIONS.md §1.4 / §2.4).

Reads ONLY the committed `corpus/` — never the network. Raises typed errors that
the tool layer maps to the closed envelope enum (§2.1):

- `SnapshotReadError`  → `SNAPSHOT_READ_ERROR` — the corpus is structurally broken
  (no `SNAPSHOT.lock`, so we cannot even name the snapshot). A *per-package* file
  simply being absent is NOT this — it is NOT_FOUND (ok/empty) at the tool layer.
- `SnapshotMalformed`  → `SNAPSHOT_MALFORMED` — an expected JSON file failed to parse.

The `corpus_snapshot_id` is read once from `SNAPSHOT.lock` and cached.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "corpus"

# OSV ecosystem -> deps.dev system (§0.4). Raw string comparison is forbidden.
_SYSTEM = {"npm": "npm", "PyPI": "pypi", "crates.io": "cargo", "Go": "go"}


class SnapshotError(Exception):
    """Base for corpus-access failures."""


class SnapshotReadError(SnapshotError):
    """A structurally-required corpus file is missing/unreadable (§2.1)."""


class SnapshotMalformed(SnapshotError):
    """A corpus JSON file failed to parse (§2.1)."""


class Snapshot:
    """A handle on one frozen corpus directory."""

    def __init__(self, corpus_dir: str | Path = DEFAULT_CORPUS):
        self.corpus_dir = Path(corpus_dir)
        self._snapshot_id: str | None = None

    @property
    def snapshot_id(self) -> str:
        if self._snapshot_id is None:
            lock_path = self.corpus_dir / "SNAPSHOT.lock"
            try:
                raw = lock_path.read_text()
            except OSError as exc:
                raise SnapshotReadError(f"SNAPSHOT.lock unreadable: {lock_path}") from exc
            try:
                lock = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SnapshotMalformed(f"SNAPSHOT.lock malformed: {exc}") from exc
            self._snapshot_id = lock["corpus_snapshot_id"]
        return self._snapshot_id

    def system_for(self, ecosystem: str) -> str:
        return _SYSTEM[ecosystem]

    def iter_osv(self, ecosystem: str):
        """Yield (id, record) for every OSV file under osv/<ecosystem>/, path-sorted
        (deterministic replay). Missing dir ⇒ no records; corrupt file ⇒ raises."""
        eco_dir = self.corpus_dir / "osv" / ecosystem
        if not eco_dir.is_dir():
            return
        for path in sorted(eco_dir.glob("*.json"), key=lambda p: p.name):
            try:
                yield path.stem, json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise SnapshotMalformed(f"{path} malformed: {exc}") from exc

    def read_extract(self, ecosystem: str, name: str) -> dict | None:
        """The deps.dev derived extract for (ecosystem, name), or None if the package
        is simply not in the corpus (NOT_FOUND). Corrupt file ⇒ raises."""
        path = self.corpus_dir / "depsdev_extract" / self.system_for(ecosystem) / f"{name}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise SnapshotMalformed(f"{path} malformed: {exc}") from exc
