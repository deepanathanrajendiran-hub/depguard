"""The uniform `{ok, data, error}` tool envelope (DECISIONS.md §2.1).

Exactly two branches; tools never throw. The runtime is corpus-only, so transient
network errors are physically impossible: `retryable` is always False and the error
code enum is closed.
"""

from __future__ import annotations

ERROR_CODES = frozenset(
    {"BAD_INPUT", "NOT_FOUND", "SNAPSHOT_READ_ERROR", "SNAPSHOT_MALFORMED", "RANGE_UNRESOLVABLE"}
)


def source_meta(
    *, source: str, corpus_snapshot_id: str, license: str, source_url: str | None
) -> dict:
    return {
        "source": source,
        "corpus_snapshot_id": corpus_snapshot_id,
        "license": license,
        "source_url": source_url,
    }


def ok(data: dict, meta: dict) -> dict:
    return {"ok": True, "data": {**data, "source_meta": meta}, "error": None}


def err(code: str, message: str) -> dict:
    if code not in ERROR_CODES:
        raise ValueError(f"{code!r} is not in the closed error-code enum (§2.1)")
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message, "retryable": False},
    }
