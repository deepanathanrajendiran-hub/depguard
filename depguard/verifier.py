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

from depguard.agreement import DepsDevObservation, agreement_state
from depguard.oracle import RangeUnresolvableError, record_containment, select_entries
from depguard.tools.pure import minimal_fix_gold

# DepsDevObservation is re-exported (moved to depguard.agreement for D4 tool 6 reuse).
__all__ = ["DepsDevObservation", "scoring_tier", "verify_verdict", "VerdictScore",
           "PredicateResult", "RangeScore", "verify_range_reconstruction"]

# Ecosystem-keyed scoring tiers (§1.2 / §5(c)). tests/test_verifier.py asserts
# these constants equal the normative registry (schemas/ecosystem_system_map.json).
_MINFIX_ECOSYSTEMS = frozenset({"npm", "crates.io", "Go"})
_CORPUS_ECOSYSTEMS = frozenset({"npm", "PyPI", "crates.io", "Go"})


def scoring_tier(ecosystem: str) -> str:
    if ecosystem not in _CORPUS_ECOSYSTEMS:
        raise LookupError(f"{ecosystem!r} is not a corpus ecosystem (DECISIONS.md §1.2)")
    return "membership_and_minfix" if ecosystem in _MINFIX_ECOSYSTEMS else "membership_only"


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
    agreement_gold = agreement_state(raw_contained, alias_set, depsdev)
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

@dataclass(frozen=True)
class RangeScore:
    """P5 result. `passed=None` means the alert was not scoreable at all."""
    status: str  # "scored" | "abstained" | "excluded"
    passed: bool | None
    gold_abstain: bool
    n_versions: int = 0
    n_mismatch: int = 0
    mismatches: tuple = ()
    exclusion_reason: str | None = None



def _scoreable_versions(true_record, ecosystem, name, published_versions):
    """The (version, gold_bit) pairs this record can actually decide.

    A version leaves the bitvector when the true record cannot resolve it, or when the
    string is not parseable by the ecosystem comparator at all — the frozen npm and PyPI
    lists carry artefacts like '1.3.2.win32-py2.4'. Neither side is scoreable there, so it
    must not count against an arm."""
    from depguard.comparators import VersionParseError
    from depguard.oracle import RangeUnresolvableError, record_containment

    out = []
    for version in published_versions:
        try:
            out.append(
                (version, record_containment(true_record, ecosystem, name, version).contained)
            )
        except (RangeUnresolvableError, VersionParseError):
            continue
    return out


def verify_range_reconstruction(
    proposal: dict | None,
    *,
    ecosystem: str,
    name: str,
    true_record: dict,
    published_versions: list[str],
) -> RangeScore:
    """P5 — SEMANTIC-RANGE-EQUIVALENCE (§5.1, v1.2.0). Scores a range reconstructed from
    advisory PROSE against the unredacted record, mechanically.

    Text equality is the wrong test: `last_affected: 5.1.2` and `fixed: 5.2b1` are
    different strings that mean the same thing whenever no release sits between them.
    So P5 scores BEHAVIOUR, not text. The claim is materialised against the frozen
    published-version list and both sides are run through the SAME
    `oracle.record_containment`:

        gold[v] = record_containment(true_record,          eco, name, v).contained
        pred[v] = record_containment(materialized_claim,   eco, name, v).contained

    for every published v; P5 passes iff the two bitvectors are equal. Gold and
    prediction differ only in which record was fed to one identical call, so the
    shared-oracle principle holds more literally here than anywhere else in the system
    — and no LLM judge touches the correctness path.

    ABSTENTION. A record whose prose carries no version token cannot be reconstructed by
    anything, so `redact.gold_abstains` marks it gold-ABSTAIN and the correct answer is
    to abstain. Abstaining on a decidable record is a miss; inventing a range on an
    abstain record is a miss. That asymmetry is what stops an extractor from farming the
    metric by always abstaining (or always guessing)."""
    from depguard.comparators import VersionParseError
    from depguard.oracle import RangeUnresolvableError, record_containment
    from depguard.redact import gold_abstains, materialize_proposal

    gold_abstain = gold_abstains(true_record)

    # EXCLUSION IS DECIDED FIRST, for both arms alike. The abstain short-circuit used to
    # return before the `n == 0` check below, so on a record where no published version is
    # scoreable a GUESSING arm was excluded (dropped from the denominator) while an
    # ABSTAINING arm was scored wrong. The arm that always abstains is
    # `deterministic_script` — the control the whole comparison is anchored on — so the
    # asymmetry ran against exactly the arm it must not.
    scoreable = _scoreable_versions(true_record, ecosystem, name, published_versions)
    if not scoreable and not gold_abstain:
        return RangeScore(
            status="excluded", passed=None, gold_abstain=False,
            exclusion_reason="no_scoreable_published_version",
        )

    if proposal is None or proposal.get("abstain"):
        return RangeScore(
            status="abstained", passed=gold_abstain, gold_abstain=gold_abstain,
        )
    if gold_abstain:
        return RangeScore(
            status="scored", passed=False, gold_abstain=True,
            exclusion_reason="invented_a_range_for_prose_with_no_version_token",
        )

    materialized = materialize_proposal(
        true_record, proposal, ecosystem=ecosystem, name=name,
        published=published_versions,
    )
    mismatches = []
    n = 0
    for version, gold_bit in scoreable:
        try:
            pred_bit = record_containment(
                materialized, ecosystem, name, version
            ).contained
        except (RangeUnresolvableError, VersionParseError):
            pred_bit = False  # a claim that decides nothing asserts nothing
        n += 1
        if gold_bit != pred_bit:
            mismatches.append((version, gold_bit, pred_bit))
    if n == 0:
        return RangeScore(
            status="excluded", passed=None, gold_abstain=False,
            exclusion_reason="no_scoreable_published_version",
        )
    return RangeScore(
        status="scored", passed=not mismatches, gold_abstain=False,
        n_versions=n, n_mismatch=len(mismatches), mismatches=tuple(mismatches[:8]),
    )
