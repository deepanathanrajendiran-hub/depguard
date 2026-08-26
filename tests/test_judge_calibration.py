"""The LLM judge is fenced off from the correctness path, and its calibration is a gate.

DECISIONS.md §4.3 permits an LLM judge for **soft narrative quality only** and forbids it
anywhere near verdict correctness, which is mechanical (§5). The repo's central claim is
that no reported result depends on an LLM grading an LLM, so that boundary is asserted here
STRUCTURALLY — by import graph — rather than promised in a docstring. A docstring cannot
fail CI.
"""

import ast
import json
from pathlib import Path

import pytest

from depguard.judge import LEVELS, RUBRIC, USE_JUDGE_THRESHOLD, agreement_stats

REPO = Path(__file__).resolve().parent.parent
AUDIT = REPO / "golden" / "judge_audit.jsonl"

#: Every module that can influence a reported correctness/groundedness/P5 number.
CORRECTNESS_PATH = [
    "metrics.py", "verifier.py", "oracle.py", "agreement.py", "comparators.py",
    "graph.py", "redact.py", "extractors.py", "trajectory.py", "ablation.py",
    "stats.py", "snapshot.py", "corpus_snapshot.py",
]


def _code_references(path: Path) -> set[str]:
    """Every way this module could REACH the judge in executable code: imports (top-level
    or lazy, since ast.walk descends into function bodies) and any identifier or attribute
    naming it.

    Deliberately ignores docstrings, comments and string literals. Several correctness-path
    modules mention the judge in prose precisely to say they do not use one — a raw text
    grep flags those, which is the opposite of the property under test."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
            found |= {a.asname for a in node.names if a.asname}
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return {f for f in found if f}


@pytest.mark.parametrize("module", CORRECTNESS_PATH)
def test_correctness_path_cannot_reach_the_judge(module):
    """The load-bearing assertion of §4.3. Checks direct imports AND any textual mention,
    so a late/lazy import inside a function cannot smuggle the judge in — that is exactly
    how this boundary would erode in practice."""
    path = REPO / "depguard" / module
    if not path.is_file():
        pytest.skip(f"{module} not present")
    offenders = sorted(r for r in _code_references(path) if "judge" in r.lower())
    assert not offenders, (
        f"{module} references the judge in executable code ({offenders}) — §4.3 forbids "
        "an LLM judge anywhere in the correctness path"
    )


def test_the_scoring_scripts_do_not_import_the_judge():
    for script in ("run_eval.py", "run_ablation.py", "run_prose_slice.py"):
        path = REPO / "scripts" / script
        if not path.is_file():
            continue
        offenders = sorted(r for r in _code_references(path) if "judge" in r.lower())
        assert not offenders, f"{script} reaches the judge in code: {offenders}"


# ===================================================================== #
# The audit set
# ===================================================================== #

def _audit():
    return [json.loads(ln) for ln in AUDIT.read_text().splitlines()
            if ln.strip() and "_comment" not in ln]


def test_audit_set_size_matches_the_spec():
    """§4.3 mandates a 15–20 case human audit."""
    assert 15 <= len(_audit()) <= 20


def test_audit_covers_every_rubric_level():
    labels = {r["human"] for r in _audit()}
    assert labels == set(LEVELS), f"levels missing from the audit set: {set(LEVELS) - labels}"


def test_audit_includes_traps_for_the_two_ways_a_clarity_judge_drifts():
    """A judge scoring clarity can fail in two characteristic ways: rewarding text that
    asserts CORRECTNESS (drifting into the job §4.3 forbids), and rewarding FLUENCY over
    content. The audit set must be able to catch both, or a passing kappa means little."""
    traps = [r for r in _audit() if r.get("why", "").startswith("TRAP")]
    assert len(traps) >= 3
    ids = {r["id"] for r in traps}
    assert "correctness_flavoured" in ids
    assert "confident_but_wrong" in ids


def test_every_audit_case_carries_its_reasoning():
    for r in _audit():
        assert r["why"].strip(), f"{r['id']} has no rationale"
        assert 1 <= r["human"] <= 5


def test_depguards_own_canned_note_is_in_the_audit_set():
    """`graph.py` emits a fixed string on disagree. Scoring the tool's own default honestly
    is the point — and it scores 2, because it names no version and no action."""
    canned = "OSV and deps.dev disagree on this version"
    row = next((r for r in _audit() if r["note"] == canned), None)
    assert row is not None, "the shipped canned note is not audited"
    assert row["human"] <= 2, "the canned note should not be labelled clear"
    assert canned in (REPO / "depguard" / "graph.py").read_text(), (
        "the audited canned note no longer matches what graph.py emits"
    )


# ===================================================================== #
# The statistics
# ===================================================================== #

def test_perfect_agreement_is_kappa_one():
    human = [1, 2, 3, 4, 5, 1, 5]
    assert agreement_stats(human, list(human))["kappa_quadratic"] == pytest.approx(1.0)
    assert agreement_stats(human, list(human))["exact"] == 1.0


def test_kappa_penalises_far_misses_more_than_near_ones():
    human = [1, 2, 3, 4, 5]
    near = agreement_stats(human, [2, 3, 4, 5, 4])["kappa_quadratic"]
    far = agreement_stats(human, [5, 5, 1, 1, 1])["kappa_quadratic"]
    assert near > far


def test_unscored_cases_are_reported_not_silently_dropped():
    """A judge that fails to answer must not quietly shrink the denominator — that would
    let an unreliable judge look well-calibrated on the subset it happened to manage."""
    stats = agreement_stats([1, 2, 3], [1, None, 3])
    assert stats["n"] == 2
    assert stats["unscored"] == 1


def test_empty_input_does_not_divide_by_zero():
    stats = agreement_stats([1, 2], [None, None])
    assert stats["n"] == 0 and stats["unscored"] == 2


def test_threshold_is_declared_and_not_trivially_passable():
    assert 0.5 <= USE_JUDGE_THRESHOLD <= 0.9


# ===================================================================== #
# The published rubric
# ===================================================================== #

def test_rubric_is_published_and_matches_the_code():
    published = REPO / "golden" / "judge_rubric.md"
    assert published.is_file(), "§4.3 requires a PUBLISHED rubric"
    assert RUBRIC.strip() in published.read_text(), (
        "golden/judge_rubric.md has drifted from the rubric the judge actually sends"
    )


def test_rubric_forbids_correctness_scoring_in_its_own_text():
    assert "not judge whether the underlying" in RUBRIC.lower() or \
           "do not judge" in RUBRIC.lower()
    assert "correct" in RUBRIC.lower()
