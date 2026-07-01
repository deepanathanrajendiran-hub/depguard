"""The §5 verifier: four TOTAL predicates, zero human judgment (DECISIONS.md §5).

**Same code labels gold AND scores predictions**: containment comes from
`depguard.oracle.record_containment` (shared with §2.4 tool 3) and the minimal-fix
gold comes from `depguard.tools.pure.minimal_fix_gold` (shared with §2.4 tool 5),
so the tools the agent calls at inference and this gold-labeler cannot diverge.

- P1 CONTAINMENT (actionable): affected_gold = raw_contained AND not withdrawn —
  the withdrawn override is applied HERE, so P1 and P3 cannot contradict (v1.1.0).
- P2 MINIMAL-FIXED: the locked published-grounded formula; scored ONLY on
  `membership_and_minfix` ecosystems ({npm, crates.io, Go}); withdrawn ⇒ gold None.
- P3 WITHDRAWN: withdrawn_gold = (record.withdrawn != null) — the one declared
  scoring convention (§1.5).
- P4 SOURCE-AGREEMENT: computed on RAW containment (v1.2.0), after full alias
  resolution (record id ∪ aliases). Implementation note (resolves an
  underdetermination between §0.3 and §1.3, captured by tests, amendable only with
  a failing test): `single_source` means the advisory is absent from deps.dev's
  *package-level* advisory-key union — deps.dev is silent on the advisory
  entirely. If the package-level union knows the advisory, the checked version's
  per-version keys give deps.dev's boolean, and agree/disagree is that boolean
  versus raw containment. A gold of `disagree` additionally requires the verdict's
  `reconciliation_note` to be non-empty (§3.3).

Alerts whose E_A is empty are EXCLUDED from scoring (counted, never scored false).
CORRECT = P1 ∧ P2 ∧ P3 ∧ P4, where an unscored P2 (membership_only tier) does not
count against the conjunction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from depguard.oracle import RangeUnresolvableError, record_containment, select_entries
from depguard.tools.pure import minimal_fix_gold

# Ecosystem-keyed scoring tiers (§1.2 / §5(c)). tests/test_verifier.py asserts
# these constants equal the normative registry (schemas/ecosystem_system_map.json).
_MINFIX_ECOSYSTEMS = frozenset({"npm", "crates.io", "Go"})
_CORPUS_ECOSYSTEMS = frozenset({"npm", "PyPI", "crates.io", "Go"})


def scoring_tier(ecosystem: str) -> str:
    if ecosystem not in _CORPUS_ECOSYSTEMS:
        raise LookupError(f"{ecosystem!r} is not a corpus ecosystem (DECISIONS.md §1.2)")
    return "membership_and_minfix" if ecosystem in _MINFIX_ECOSYSTEMS else "membership_only"


@dataclass(frozen=True)
class DepsDevObservation:
    """What the frozen deps.dev extract says about the checked (package, version)."""

    package_known: bool
    version_advisory_keys: list[str]  # advisoryKeys[] on the checked pinned version
    package_advisory_keys: list[str]  # union of advisoryKeys[] across all versions


@dataclass(frozen=True)
class PredicateResult:
    name: str
    passed: bool | None  # None = not scored for this alert (e.g. P2 on PyPI)
    gold: object
    actual: object


@dataclass(frozen=True)
class VerdictScore:
    status: str  # "scored" | "excluded"
    exclusion_reason: str | None
    predicates: dict[str, PredicateResult] = field(default_factory=dict)
    correct: bool | None = None
    agreement_metric_eligible: bool = True  # False when P4 gold is single_source


def _excluded(reason: str) -> VerdictScore:
    return VerdictScore(
        status="excluded", exclusion_reason=reason,
        predicates={}, correct=None, agreement_metric_eligible=False,
    )


def _agreement_gold(
    raw_contained: bool, alias_set: frozenset[str], depsdev: DepsDevObservation | None
) -> str:
    if depsdev is None or not depsdev.package_known:
        return "single_source"
    if not alias_set & set(depsdev.package_advisory_keys):
        return "single_source"  # silent after full alias resolution (§0.3)
    depsdev_says_affected = bool(alias_set & set(depsdev.version_advisory_keys))
    return "agree" if depsdev_says_affected == raw_contained else "disagree"


def verify_verdict(
    verdict: dict,
    *,
    ecosystem: str,
    name: str,
    pinned_version: str,
    osv_record: dict,
    published_versions: list[str],
    depsdev: DepsDevObservation | None,
) -> VerdictScore:
    """Score one Verdict (§3.3) against gold computed from the frozen evidence."""
    if not select_entries(osv_record, ecosystem, name):
        return _excluded("empty_e_a_after_membership_filter")

    try:
        containment = record_containment(osv_record, ecosystem, name, pinned_version)
    except RangeUnresolvableError:
        return _excluded("range_unresolvable")

    raw_contained = containment.contained
    withdrawn_gold = osv_record.get("withdrawn") is not None

    # P1 — actionable affected (withdrawn override folded in, v1.1.0)
    affected_gold = raw_contained and not withdrawn_gold
    p1 = PredicateResult("P1", verdict["affected"] == affected_gold,
                         affected_gold, verdict["affected"])

    # P2 — minimal fixed, minfix tier only
    if scoring_tier(ecosystem) == "membership_and_minfix":
        min_fixed_gold, _reason, _considered = minimal_fix_gold(
            ecosystem, name, pinned_version, osv_record, published_versions
        )
        p2 = PredicateResult("P2", verdict["minimal_fixed_version"] == min_fixed_gold,
                             min_fixed_gold, verdict["minimal_fixed_version"])
    else:
        p2 = PredicateResult("P2", None, None, verdict["minimal_fixed_version"])

    # P3 — withdrawn (declared convention, §1.5)
    p3 = PredicateResult("P3", verdict["withdrawn"] == withdrawn_gold,
                         withdrawn_gold, verdict["withdrawn"])

    # P4 — source agreement on RAW containment (v1.2.0), full alias resolution
    alias_set = frozenset({osv_record["id"], *osv_record.get("aliases", [])})
    agreement_gold = _agreement_gold(raw_contained, alias_set, depsdev)
    p4_passed = verdict["source_agreement"] == agreement_gold
    if agreement_gold == "disagree" and not verdict.get("reconciliation_note"):
        p4_passed = False  # §3.3: note MUST be non-empty on disagree
    p4 = PredicateResult("P4", p4_passed, agreement_gold, verdict["source_agreement"])

    predicates = {"P1": p1, "P2": p2, "P3": p3, "P4": p4}
    correct = all(p.passed is not False for p in predicates.values())
    return VerdictScore(
        status="scored",
        exclusion_reason=None,
        predicates=predicates,
        correct=correct,
        agreement_metric_eligible=agreement_gold != "single_source",
    )
