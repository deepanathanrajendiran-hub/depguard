"""Source-agreement core (DECISIONS.md §0.3 / §5 P4) — the ONE definition of
`agree | disagree | single_source`, imported by BOTH the §5 verifier (gold labeler)
and §2.4 tool 6 `crosscheck_second_source` (the agent-facing tool), so they cannot
diverge (handoff house rule 3, shared-oracle principle).

Agreement is computed on RAW containment (pre-withdrawn-override, v1.2.0): the
withdrawn override is an actionability rule, not a source conflict.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DepsDevObservation:
    """What the frozen deps.dev extract says about the checked (package, version)."""

    package_known: bool
    version_advisory_keys: list[str]  # advisoryKeys[] on the checked pinned version
    package_advisory_keys: list[str]  # union of advisoryKeys[] across all keyed versions
    version_known: bool = True  # was the checked version present in the extract's keyed set?


def agreement_state(
    raw_contained: bool, alias_set: frozenset[str], depsdev: DepsDevObservation | None
) -> str:
    """§5 P4 gold: `agree | disagree | single_source` after full alias resolution.

    A `disagree` requires a GENUINE per-version contradiction (§1.3): OSV and
    deps.dev must disagree on a version deps.dev actually has data for. If the frozen
    extract carries NO per-version keys for the checked version (`version_known` is
    False — e.g. it fell outside the freeze's keyed-version budget), deps.dev is
    SILENT on that version and we return `single_source` — never a fabricated
    disagreement (the §1.3 integrity rule: do not manufacture disagreements)."""
    if depsdev is None or not depsdev.package_known:
        return "single_source"
    if not alias_set & set(depsdev.package_advisory_keys):
        return "single_source"  # deps.dev silent on the advisory after alias resolution
    if not depsdev.version_known:
        return "single_source"  # deps.dev silent on THIS version — no contradiction to assert
    depsdev_says_affected = bool(alias_set & set(depsdev.version_advisory_keys))
    return "agree" if depsdev_says_affected == raw_contained else "disagree"


def observe_from_extract(extract: dict | None, version: str) -> DepsDevObservation:
    """Build a `DepsDevObservation` from a frozen deps.dev extract (§1.7b) for one
    checked version. The package-level key union is derived from the keyed-version
    subset the freeze captured (which always includes the advisory's affected
    boundary versions — see scripts/freeze_micro.py:relevant_versions)."""
    if extract is None:
        return DepsDevObservation(False, [], [], version_known=False)
    by_version = extract.get("advisory_keys_by_version", {})
    version_keys = list(by_version.get(version, []))
    package_keys = sorted({k for keys in by_version.values() for k in keys})
    return DepsDevObservation(
        True, version_keys, package_keys, version_known=version in by_version
    )
