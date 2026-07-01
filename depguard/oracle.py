"""The shared containment core (DECISIONS.md §2.4 tool 3 ⇄ §5 entry selection).

This module is THE oracle logic: `check_version_affected` (the tool the agent calls
at inference) and the §5 verifier (which labels gold and scores predictions) both
import it, so they cannot diverge on multi-`affected[]` records — the v1.3.0
requirement.

Semantics implemented here, in DECISIONS.md terms:
- E_A selection (§5): entries whose `package.ecosystem == ecosystem` AND
  `package.name == name`, canonical OSV casing.
- OR-aggregation over E_A; ECOSYSTEM/GIT-only (or otherwise undecidable) entries
  ABSTAIN. Empty E_A ⇒ contained=False (excluded at scoring, never scored false).
  Non-empty E_A where EVERY entry abstains ⇒ RANGE_UNRESOLVABLE — never a silent
  judgment-call verdict (§2.4 step 4).
- SEMVER interval events (§2.4/§5 P1): `introduced` opens (the literal "0" = −∞),
  `fixed` closes exclusive `[introduced, fixed)`, `last_affected` closes inclusive
  `[introduced, last_affected]`. A `limit` event (GIT-oriented per OSV; not expected
  post-curation in SEMVER ranges) is treated as an exclusive close — the
  conservative mechanical reading.
- versions_list membership is comparator-EQUALITY; unparseable list items are
  skipped (curation's drop-on-ambiguity means they should not occur).
- Containment here is RAW: the withdrawn override is a verdict-layer product rule
  (§1.5, §5 P1) and deliberately does not exist in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from depguard.comparators import VersionParseError, get_comparator


class RangeUnresolvableError(Exception):
    """E_A is non-empty but no entry is mechanically decidable (§2.4 step 4)."""


@dataclass(frozen=True)
class Containment:
    contained: bool
    matched_by: str | None  # "versions_list" | "semver_range" | None
    matched_range: dict | None  # {"introduced", "fixed", "last_affected"} | None
    e_a_empty: bool


def select_entries(osv_record: dict, ecosystem: str, name: str) -> list[dict]:
    """E_A: the affected[] entries matching (ecosystem, name) exactly (§5)."""
    return [
        entry
        for entry in osv_record.get("affected", [])
        if entry.get("package", {}).get("ecosystem") == ecosystem
        and entry.get("package", {}).get("name") == name
    ]


def _intervals(events: list[dict]):
    """Yield (lower, upper, upper_inclusive, citation) from an OSV event list.

    Each event object carries EXACTLY ONE of introduced|fixed|last_affected|limit —
    iterate and switch on the key, never pair positionally (§1.1).
    """
    lower = None
    citation = None
    for event in events:
        if len(event) != 1:
            raise VersionParseError(f"OSV event must carry exactly one key: {event!r}")
        ((kind, value),) = event.items()
        if kind == "introduced":
            if lower is not None:
                # previous interval never closed: open-ended
                yield lower, None, False, citation
            lower = value
            citation = {"introduced": value, "fixed": None, "last_affected": None}
        elif kind in ("fixed", "limit"):
            if lower is not None:
                citation = dict(citation, fixed=value) if kind == "fixed" else citation
                yield lower, value, False, citation
                lower, citation = None, None
        elif kind == "last_affected":
            if lower is not None:
                citation = dict(citation, last_affected=value)
                yield lower, value, True, citation
                lower, citation = None, None
        else:
            raise VersionParseError(f"unknown OSV event key {kind!r}")
    if lower is not None:
        yield lower, None, False, citation


def _entry_containment(entry: dict, ecosystem: str, version_key) -> Containment | None:
    """Containment for ONE entry; None means the entry ABSTAINS (undecidable)."""
    comparator = get_comparator(ecosystem)
    decidable = False

    # versions_list membership by comparator equality (checked first)
    for candidate in entry.get("versions") or []:
        try:
            candidate_key = comparator.key(candidate)
        except VersionParseError:
            continue  # drop-on-ambiguity artifact; skip the item
        decidable = True
        if candidate_key == version_key:
            return Containment(True, "versions_list", None, e_a_empty=False)

    # SEMVER ranges
    for range_ in entry.get("ranges") or []:
        if range_.get("type") != "SEMVER":
            continue  # ECOSYSTEM/GIT ranges abstain (§2.4 step 3)
        try:
            for lower, upper, inclusive, citation in list(_intervals(range_.get("events", []))):
                decidable = True
                if lower == "0":
                    above_lower = True  # "0" = −∞
                else:
                    above_lower = comparator.key(lower) <= version_key
                if not above_lower:
                    continue
                if upper is None:
                    return Containment(True, "semver_range", citation, e_a_empty=False)
                upper_key = comparator.key(upper)
                if (version_key <= upper_key) if inclusive else (version_key < upper_key):
                    return Containment(True, "semver_range", citation, e_a_empty=False)
        except VersionParseError:
            continue  # unparseable bound: this range abstains

    if not decidable:
        return None
    return Containment(False, None, None, e_a_empty=False)


def record_containment(osv_record: dict, ecosystem: str, name: str, version: str) -> Containment:
    """RAW containment of `version` in `osv_record`, OR-aggregated over E_A.

    Raises VersionParseError if `version` itself fails the vetted comparator
    (caller maps to BAD_INPUT) and RangeUnresolvableError if E_A is non-empty but
    entirely undecidable (caller maps to RANGE_UNRESOLVABLE).
    """
    comparator = get_comparator(ecosystem)
    version_key = comparator.key(version)  # VersionParseError propagates

    entries = select_entries(osv_record, ecosystem, name)
    if not entries:
        return Containment(False, None, None, e_a_empty=True)

    any_decidable = False
    for entry in entries:
        result = _entry_containment(entry, ecosystem, version_key)
        if result is None:
            continue  # abstain
        any_decidable = True
        if result.contained:
            return result  # first entry that produced true supplies the citation

    if not any_decidable:
        raise RangeUnresolvableError(
            f"every matching affected[] entry for {ecosystem}/{name} in "
            f"{osv_record.get('id')!r} is undecidable (ECOSYSTEM/GIT-only or unparseable)"
        )
    return Containment(False, None, None, e_a_empty=False)
