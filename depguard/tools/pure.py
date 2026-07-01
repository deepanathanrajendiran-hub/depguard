"""The three PURE tools (DECISIONS.md §2.4 tools 1, 3, 5).

All three are deterministic, take no snapshot dependency at call time (the caller
stamps the active `corpus_snapshot_id` into `source_meta`), and NEVER throw —
every failure is an envelope error (§2.1).
"""

from __future__ import annotations

import json
import re

from depguard import envelope
from depguard.comparators import VersionParseError, get_comparator
from depguard.oracle import RangeUnresolvableError, record_containment

_LOCAL_LICENSE = "CC0-1.0"

# v0.1 manifest parsing scope (plan D2): real npm package.json + PyPI flat JSON.
# crates.io/Go are corpus ecosystems but their parsers are backlog items.
_PARSER_ECOSYSTEMS = {"npm", "PyPI"}

_SEMVERISH = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.\-]+)?(?:\+[0-9A-Za-z.\-]+)?")


def _local_meta(corpus_snapshot_id: str) -> dict:
    return envelope.source_meta(
        source="local",
        corpus_snapshot_id=corpus_snapshot_id,
        license=_LOCAL_LICENSE,
        source_url=None,
    )


# =====================================================================
# Tool 1: parse_manifest
# =====================================================================

def _parse_npm_spec(spec: str, comparator):
    """Return (version, pinned) or None if the spec is not version-shaped."""
    try:
        comparator.key(spec)
        return spec, True  # exact semver ⇒ pinned
    except VersionParseError:
        pass
    if spec[:1] in ("^", "~"):
        candidate = spec[1:]
        try:
            comparator.key(candidate)
            return candidate, False
        except VersionParseError:
            pass
    match = _SEMVERISH.search(spec)
    if match:
        candidate = match.group(0)
        try:
            comparator.key(candidate)
            return candidate, False  # best-effort version from a range spec
        except VersionParseError:
            pass
    return None


def _pep503_normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_manifest(
    ecosystem: str, manifest_filename: str, manifest_text: str, *, corpus_snapshot_id: str
) -> dict:
    """§2.4 tool 1. npm: real package.json (dependencies + devDependencies).
    PyPI: flat JSON `{name: version}` fallback. Ranges/caret/tilde ⇒ pinned=False
    with a best-effort version; unparseable specs land in `unparsed_lines`."""
    if ecosystem not in _PARSER_ECOSYSTEMS:
        return envelope.err(
            "BAD_INPUT",
            f"no v0.1 manifest parser for ecosystem {ecosystem!r} "
            f"(supported: {sorted(_PARSER_ECOSYSTEMS)})",
        )
    if not manifest_text or not manifest_text.strip():
        return envelope.err("BAD_INPUT", "manifest_text is empty")
    try:
        document = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        return envelope.err("BAD_INPUT", f"manifest is not valid JSON: {exc}")
    if not isinstance(document, dict):
        return envelope.err("BAD_INPUT", "manifest JSON must be an object")

    dependencies: list[dict] = []
    unparsed: list[str] = []

    if ecosystem == "npm":
        comparator = get_comparator("npm")
        for section in ("dependencies", "devDependencies"):
            entries = document.get(section) or {}
            if not isinstance(entries, dict):
                unparsed.append(f"{section}: expected an object")
                continue
            for name, spec in entries.items():
                if not isinstance(spec, str):
                    unparsed.append(f"{name}@{spec!r}")
                    continue
                parsed = _parse_npm_spec(spec, comparator)
                if parsed is None:
                    unparsed.append(f"{name}@{spec}")
                    continue
                version, pinned = parsed
                dependencies.append(
                    {"ecosystem": "npm", "name": name, "version": version, "pinned": pinned}
                )
    else:  # PyPI flat JSON
        comparator = get_comparator("PyPI")
        for name, spec in document.items():
            if not isinstance(spec, str):
                unparsed.append(f"{name}@{spec!r}")
                continue
            try:
                comparator.key(spec)
            except VersionParseError:
                unparsed.append(f"{name}@{spec}")
                continue
            dependencies.append(
                {
                    "ecosystem": "PyPI",
                    "name": _pep503_normalize(name),
                    "version": spec,
                    "pinned": True,
                }
            )

    return envelope.ok(
        {"dependencies": dependencies, "unparsed_lines": unparsed},
        _local_meta(corpus_snapshot_id),
    )


# =====================================================================
# Tool 3: check_version_affected — RAW containment only (§2.4 tool 3)
# =====================================================================

def check_version_affected(
    ecosystem: str, name: str, version: str, osv_record: dict, *, corpus_snapshot_id: str
) -> dict:
    """RAW range containment. Deliberately does NOT apply the withdrawn override
    (a verdict-layer product rule, §1.5/§5 P1); it surfaces `withdrawn_timestamp`
    verbatim so the verdict layer can."""
    try:
        get_comparator(ecosystem)
    except LookupError as exc:
        return envelope.err("BAD_INPUT", str(exc))
    try:
        containment = record_containment(osv_record, ecosystem, name, version)
    except VersionParseError as exc:
        return envelope.err("BAD_INPUT", str(exc))
    except RangeUnresolvableError as exc:
        return envelope.err("RANGE_UNRESOLVABLE", str(exc))

    return envelope.ok(
        {
            "contained": containment.contained,
            "matched_by": containment.matched_by,
            "matched_range": containment.matched_range,
            "withdrawn_timestamp": osv_record.get("withdrawn"),
        },
        _local_meta(corpus_snapshot_id),
    )


# =====================================================================
# Tool 5: compute_minimal_fix (§2.4 tool 5 — LOCKED definition)
# =====================================================================

def minimal_fix_gold(
    ecosystem: str, name: str, current_version: str, osv_record: dict,
    published_versions: list[str],
):
    """The LOCKED minimal-fix formula, shared verbatim with §5 P2 gold labeling:
    smallest PUBLISHED V >= current with raw containment false; None if none.

    Returns (minimal_fixed_version | None, reason, candidates_considered).
    Raises VersionParseError / RangeUnresolvableError for the caller to map.
    """
    if osv_record.get("withdrawn") is not None:
        return None, "withdrawn_non_actionable", []

    comparator = get_comparator(ecosystem)
    current_key = comparator.key(current_version)  # VersionParseError propagates

    parseable = []
    for candidate in published_versions:
        try:
            comparator.key(candidate)
        except VersionParseError:
            continue  # cannot be ordered ⇒ never selected
        parseable.append(candidate)
    candidates = [v for v in comparator.sort(parseable) if comparator.key(v) >= current_key]

    current_contained = record_containment(osv_record, ecosystem, name, current_version).contained

    considered: list[str] = []
    minimal_fixed = None
    for candidate in candidates:
        considered.append(candidate)
        if not record_containment(osv_record, ecosystem, name, candidate).contained:
            minimal_fixed = candidate
            break

    if not current_contained:
        reason = "already_safe"
    elif minimal_fixed is not None:
        reason = "published_version_clears"
    else:
        reason = "no_fix_available"
    return minimal_fixed, reason, considered


def compute_minimal_fix(
    ecosystem: str, name: str, current_version: str, osv_record: dict,
    published_versions: list[str], *, corpus_snapshot_id: str
) -> dict:
    """§2.4 tool 5. WITHDRAWN SHORT-CIRCUIT first (v1.1.0): a withdrawn advisory is
    non-actionable, so the tool never chases a fix for a vulnerability that no
    longer legally exists. Otherwise the LOCKED published-grounded formula, via the
    same helper the §5 P2 gold labeler uses."""
    try:
        get_comparator(ecosystem)
    except LookupError as exc:
        return envelope.err("BAD_INPUT", str(exc))
    try:
        minimal_fixed, reason, considered = minimal_fix_gold(
            ecosystem, name, current_version, osv_record, published_versions
        )
    except VersionParseError as exc:
        return envelope.err("BAD_INPUT", str(exc))
    except RangeUnresolvableError as exc:
        return envelope.err("RANGE_UNRESOLVABLE", str(exc))

    return envelope.ok(
        {
            "minimal_fixed_version": minimal_fixed,
            "reason": reason,
            "candidates_considered": considered,
        },
        _local_meta(corpus_snapshot_id),
    )
