"""The three EXTERNAL snapshot-backed tools (DECISIONS.md §2.4 tools 2, 4, 6).

`osv_query_package` (OSV), `resolve_published_versions` + `crosscheck_second_source`
(deps.dev). They read ONLY the frozen corpus via `depguard.snapshot.Snapshot` — so
they ARE the deterministic CI mocks; there is no separate mock layer. They never
throw (§2.1): every failure is an envelope error. Tool 6 reuses the SAME
`depguard.agreement.agreement_state` the §5 verifier uses (shared-oracle principle).

No network reference lives in this layer — the deps.dev attribution URL is read from
the frozen extract's `_provenance`, never constructed here (verified by a grep test).
"""

from __future__ import annotations

from depguard import envelope
from depguard.agreement import agreement_state, observe_from_extract
from depguard.comparators import VersionParseError, get_comparator
from depguard.snapshot import Snapshot, SnapshotMalformed, SnapshotReadError


def _map_snapshot_error(exc: Exception) -> dict:
    if isinstance(exc, SnapshotMalformed):
        return envelope.err("SNAPSHOT_MALFORMED", str(exc))
    return envelope.err("SNAPSHOT_READ_ERROR", str(exc))


def _deps_meta(snapshot_id: str, extract: dict | None) -> dict:
    url = None
    if extract:
        url = (extract.get("_provenance") or {}).get("source_url")
    return envelope.source_meta(
        source="deps.dev", corpus_snapshot_id=snapshot_id, license="CC-BY-4.0", source_url=url
    )


# --------------------------------------------------------------------------- #
# Tool 2: osv_query_package
# --------------------------------------------------------------------------- #

def _entry_matches(entry: dict, ecosystem: str, name: str) -> bool:
    pkg = entry.get("package") or {}
    return pkg.get("ecosystem") == ecosystem and pkg.get("name") == name


def _entry_decidable(entry: dict, ecosystem: str) -> tuple[bool, str | None]:
    """Curation decidability (§1.2): SEMVER range OR parseable non-empty versions[]."""
    cmp = get_comparator(ecosystem)
    if [r for r in entry.get("ranges") or [] if r.get("type") == "SEMVER"]:
        return True, None
    versions = entry.get("versions") or []
    if versions:
        for v in versions:
            try:
                cmp.key(v)
            except VersionParseError:
                return False, "NON_SEMVER_VERSION_STRING"
        return True, None
    types = {r.get("type") for r in entry.get("ranges") or []}
    if types == {"GIT"}:
        return False, "GIT_ONLY"
    return False, "ECOSYSTEM_RANGE_ONLY"


def osv_query_package(
    ecosystem: str, name: str, version: str | None = None, *, snapshot: Snapshot
) -> dict:
    """§2.4 tool 2. Returns the corpus advisories affecting (ecosystem, name).
    Enforces §1.2: a record whose only entries for this package are
    ECOSYSTEM/GIT-only-no-versions lands in `excluded[{id,reason}]`, not `advisories`.
    Absence ⇒ ok with empty lists (NOT_FOUND is not an error). `version` is accepted
    for OSV `/v1/query` parity; retrieval is package-scoped in v0.1 (containment is
    the separate `check_version_affected` step)."""
    try:
        snapshot_id = snapshot.snapshot_id
        get_comparator(ecosystem)  # unknown ecosystem ⇒ LookupError ⇒ BAD_INPUT
        advisories, excluded = [], []
        for rid, rec in snapshot.iter_osv(ecosystem):
            entries = [e for e in rec.get("affected", []) if _entry_matches(e, ecosystem, name)]
            if not entries:
                continue
            decidable = False
            reason = None
            for e in entries:
                ok, drop_reason = _entry_decidable(e, ecosystem)
                if ok:
                    decidable = True
                elif reason is None:
                    reason = drop_reason
            if decidable:
                advisories.append(rec)
            else:
                excluded.append({"id": rid, "reason": reason or "EXCLUDED"})
    except (SnapshotMalformed, SnapshotReadError) as exc:
        return _map_snapshot_error(exc)
    except LookupError as exc:
        return envelope.err("BAD_INPUT", str(exc))

    license = (
        "CC-BY-4.0"
        if any(a.get("_provenance", {}).get("license") == "CC-BY-4.0" for a in advisories)
        else "CC0-1.0"
    )
    return envelope.ok(
        {"advisories": advisories, "excluded": excluded, "corpus_snapshot_id": snapshot_id},
        envelope.source_meta(
            source="osv", corpus_snapshot_id=snapshot_id, license=license, source_url=None
        ),
    )


# --------------------------------------------------------------------------- #
# Tool 4: resolve_published_versions
# --------------------------------------------------------------------------- #

def _ascending(versions: list[str], cmp) -> list[str]:
    parseable, other = [], []
    for v in versions:
        try:
            cmp.key(v)
            parseable.append(v)
        except VersionParseError:
            other.append(v)  # unorderable — appended after the ordered block
    return cmp.sort(parseable) + sorted(other)


def resolve_published_versions(ecosystem: str, name: str, *, snapshot: Snapshot) -> dict:
    """§2.4 tool 4. Published-version list from the frozen deps.dev extract, sorted
    ascending by the ecosystem comparator — the load-bearing second signal that
    grounds minimal-fix in real releases (§1.3). Absence ⇒ ok with empty versions."""
    try:
        snapshot_id = snapshot.snapshot_id
        cmp = get_comparator(ecosystem)
        extract = snapshot.read_extract(ecosystem, name)
    except (SnapshotMalformed, SnapshotReadError) as exc:
        return _map_snapshot_error(exc)
    except LookupError as exc:
        return envelope.err("BAD_INPUT", str(exc))

    meta = _deps_meta(snapshot_id, extract)
    if extract is None:
        return envelope.ok(
            {"versions": [], "default_version": None, "source": "deps.dev",
             "corpus_snapshot_id": snapshot_id},
            meta,
        )
    return envelope.ok(
        {
            "versions": _ascending(extract.get("versions", []), cmp),
            "default_version": extract.get("default_version"),
            "source": "deps.dev",
            "corpus_snapshot_id": snapshot_id,
        },
        meta,
    )


# --------------------------------------------------------------------------- #
# Tool 6: crosscheck_second_source
# --------------------------------------------------------------------------- #

def crosscheck_second_source(
    ecosystem: str, name: str, version: str, osv_verdict: dict, *, snapshot: Snapshot
) -> dict:
    """§2.4 tool 6. Cross-checks OSV's RAW containment against deps.dev's per-version
    advisory keys, via the shared `agreement_state` (§5 P4). `osv_verdict` carries
    `{contained, advisory_id, aliases}` — fed from `check_version_affected.contained`,
    NOT the withdrawn-adjusted Verdict.affected (§0.3). `cvss3_score` is display-only
    and null in v0.1 (the extract carries no severity)."""
    try:
        snapshot_id = snapshot.snapshot_id
        get_comparator(ecosystem)
        extract = snapshot.read_extract(ecosystem, name)
    except (SnapshotMalformed, SnapshotReadError) as exc:
        return _map_snapshot_error(exc)
    except LookupError as exc:
        return envelope.err("BAD_INPUT", str(exc))

    alias_set = frozenset({osv_verdict["advisory_id"], *osv_verdict.get("aliases", [])})
    obs = observe_from_extract(extract, version)
    agreement = agreement_state(bool(osv_verdict["contained"]), alias_set, obs)
    per_version = bool(alias_set & set(obs.version_advisory_keys))
    return envelope.ok(
        {
            "agreement": agreement,
            "second_source": "deps.dev",
            "second_source_advisory_keys": list(obs.version_advisory_keys),
            "per_version_affected_bool": per_version,
            "cvss3_score": None,
            "corpus_snapshot_id": snapshot_id,
        },
        _deps_meta(snapshot_id, extract),
    )
