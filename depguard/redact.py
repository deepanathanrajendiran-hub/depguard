"""The prose slice (DECISIONS.md §5.1, v1.2.0): make the task undecidable by grammar.

WHY THIS EXISTS. Version-range triage over a frozen corpus is mechanically decidable, so
a plain semver-containment script solves it at 1.0000 and the LLM arms can at best tie —
which is exactly what v0.1 measured. A tie was the ceiling before any code ran, so the
comparison carried no information. The fix is not to reframe the tie; it is to add a
slice where the deterministic path PROVABLY cannot succeed, while the verifier stays
100% mechanical.

WHAT IS REDACTED. `redact_ranges` drops `ranges` and `versions` from every `affected[]`
entry and keeps everything else — package, id, aliases, withdrawn, summary, details,
references. It is a pure function of already-frozen bytes: the corpus directory is never
touched, `corpus_snapshot_id` is unchanged, every v0.1 number stays reproducible, and
the slice is byte-reproducible because redaction is deterministic.

WHY THE SCRIPT PROVABLY FAILS. `oracle._entry_containment` decides containment from
`versions[]` membership or a SEMVER range, and ECOSYSTEM/GIT ranges abstain by design
(§2.4 step 3). Strip both and every entry abstains, so `record_containment` raises
`RangeUnresolvableError`. That is a raised exception asserted by a committed test, not a
measured shortfall you have to argue about. The affected range now exists ONLY in the
`details` prose, which no grammar recovers — all 40 corpus records carry non-empty
details (median 414 chars) and 34 of 40 carry a version token.

HOW A RECONSTRUCTION IS SCORED. See `verifier.verify_range_reconstruction` (P5). The
claim is materialised against the frozen published-version list and compared to the
unredacted record by containment bitvector — the SAME `record_containment` on both
sides, so the shared-oracle principle is preserved more literally than before: gold and
prediction differ only in which record was fed to the identical call.
"""

from __future__ import annotations

import copy
import re

from depguard.comparators import VersionParseError, get_comparator

__all__ = [
    "redact_ranges", "prose_of", "has_version_token", "gold_abstains",
    "materialize_proposal", "expand_events",
]

# A version token in free text: 1.2, 1.2.3, 5.2b1, 2.0.0rc1, 2024.7.4.
_VERSION_TOKEN = re.compile(r"\b\d+\.\d+(?:\.\d+)*(?:[._-]?(?:a|b|c|rc|alpha|beta|dev|post)\d*)?\b")


def redact_ranges(record: dict) -> dict:
    """Drop every machine-readable affected-range signal, keep the prose.

    Pure: the input record is not mutated and the corpus is never written."""
    out = copy.deepcopy(record)
    for entry in out.get("affected") or []:
        entry.pop("ranges", None)
        entry["versions"] = []
    return out


def prose_of(record: dict) -> str:
    """The only surviving description of the affected range: summary + details."""
    return f"{record.get('summary') or ''}\n\n{record.get('details') or ''}".strip()


def has_version_token(text: str) -> bool:
    return bool(_VERSION_TOKEN.search(text or ""))


def gold_abstains(record: dict) -> bool:
    """A seed is gold-ABSTAIN when its prose carries no version token at all: nothing
    could recover the range from it, so abstaining is the correct answer and inventing
    a range is wrong. Determined mechanically from frozen bytes, so it stays
    byte-reproducible and no human judgement enters the label."""
    return not has_version_token(prose_of(record))


def expand_events(events: list[dict], published: list[str], ecosystem: str) -> list[str]:
    """Expand proposed OSV interval events into the subset of PUBLISHED versions they
    cover, applying the OSV spec exactly as `oracle._intervals` does: `introduced`
    opens inclusive ("0" = -inf), `fixed` closes exclusive, `last_affected` closes
    inclusive, sibling intervals OR together, and an `introduced` that is never closed
    runs to +inf — including one interrupted by the next `introduced`.

    That last rule is not a detail. P5's premise is that the same semantics apply on both
    sides of the comparison, so a malformed proposal must expand exactly as the identical
    events would behave inside a real record. Dropping a dangling `introduced` here (an
    easy shortcut) would score a sloppy reconstruction differently from the way the oracle
    would actually read it.

    Expansion is relative to the frozen published list on purpose. Containment over REAL
    releases is the only thing the verdict and minimal-fix consume, so two reconstructions
    that differ only where no release exists (`last_affected: 5.1.2` vs `fixed: 5.2b1`)
    are semantically identical and must score identically."""
    comparator = get_comparator(ecosystem)
    keyed = []
    for v in published:
        try:
            keyed.append((v, comparator.key(v)))
        except VersionParseError:
            continue  # unparseable published version: not scoreable either side

    covered: set[str] = set()
    lower = None
    for event in events or []:
        if not isinstance(event, dict) or len(event) != 1:
            continue  # malformed event: ignore rather than crash the arm
        ((kind, value),) = event.items()
        if kind == "introduced":
            if lower is not None:
                # previous interval never closed → open-ended (oracle._intervals)
                covered |= _covered(keyed, comparator, lower, None, False)
            lower = value
        elif kind in ("fixed", "last_affected"):
            if lower is None:
                continue
            covered |= _covered(keyed, comparator, lower, value, kind == "last_affected")
            lower = None
    if lower is not None:  # a trailing unclosed interval also runs to +inf
        covered |= _covered(keyed, comparator, lower, None, False)
    return sorted(covered)


def _covered(keyed, comparator, lower, upper, inclusive) -> set[str]:
    try:
        lower_key = None if lower == "0" else comparator.key(lower)
        upper_key = None if upper is None else comparator.key(upper)
    except VersionParseError:
        return set()  # an unparseable proposed bound covers nothing
    out = set()
    for version, key in keyed:
        if lower_key is not None and not (lower_key <= key):
            continue
        if upper_key is None:
            out.add(version)
        elif (key <= upper_key) if inclusive else (key < upper_key):
            out.add(version)
    return out


def materialize_proposal(
    true_record: dict, proposal: dict, *, ecosystem: str, name: str,
    published: list[str],
) -> dict:
    """Turn an extractor's `{events, versions}` claim into a record the SAME oracle can
    score, by reducing it to the set of published versions it asserts are affected.

    Uniform across ecosystems by design: npm decides containment from SEMVER ranges and
    PyPI from enumerated `versions[]` (ECOSYSTEM ranges abstain, §2.4 step 3), so an
    extractor that had to emit the ecosystem's native representation would be doing two
    different jobs. Reducing every claim to "which published releases are affected"
    gives one task, one scoring rule, and one code path."""
    claimed = set(proposal.get("versions") or [])
    claimed |= set(expand_events(proposal.get("events") or [], published, ecosystem))
    claimed &= set(published)  # a claim about an unpublished version is unscoreable
    out = copy.deepcopy(true_record)
    for entry in out.get("affected") or []:
        entry.pop("ranges", None)
        entry["versions"] = sorted(claimed)
    return out
