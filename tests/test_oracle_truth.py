"""The independent oracle check the eval gate structurally cannot be.

`scripts/run_eval.py` recomputes gold with `build_gold()` at gate time, and
`tools/pure.py::compute_minimal_fix` delegates to `minimal_fix_gold` — the very
function that labels gold. Prediction and label therefore move TOGETHER: a sign flip
inside `depguard/oracle.py` changes both, and `correctness` stays pinned at 1.0000.

That is not a hypothesis. Inverting the `fixed` event's upper bound from exclusive to
inclusive — a real semver bug meaning "the patched release is still vulnerable" —
flips 13 of the 29 golden verdicts, including `seed_01` (lodash 4.17.21, the case the
README leads with, which then recommends 4.17.23), and the aggregate reads:

    tool_selection 1.0000  verdict_yield 1.0000  plan_adherence 1.0000
    groundedness   0.9655  correctness   1.0000        <- unchanged

The gate went red only via one incidental groundedness row on a seed that was not one
of the 13. Correctness — the headline metric — never moved.

`golden/oracle_truth.jsonl` closes that hole. Its rows were written BY HAND from each
advisory's range events against the OSV spec, never by running the oracle, and they are
weighted toward boundaries because a boundary is where a sign flip shows. The shared
oracle stays the scorer (that design is right and stays); this is the outside check on
the oracle itself.

Division of labour, stated plainly for the README:
    eval gate         -> catches orchestration regressions (plan, tools, evidence)
    oracle truth table -> catches oracle bugs
"""

import json
from pathlib import Path

import pytest

from depguard.oracle import record_containment
from depguard.snapshot import Snapshot

REPO = Path(__file__).resolve().parent.parent
TRUTH = REPO / "golden" / "oracle_truth.jsonl"


def _rows():
    out = []
    for line in TRUTH.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "_comment" in row:  # the header row documents provenance
            continue
        out.append(row)
    return out


ROWS = _rows()
IDS = [f"{r['name']}@{r['version']}:{r['advisory_id']}" for r in ROWS]


@pytest.fixture(scope="module")
def snap():
    return Snapshot()


def _record(row):
    path = REPO / "corpus" / "osv" / row["ecosystem"] / f"{row['advisory_id']}.json"
    return json.loads(path.read_text())


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_oracle_matches_hand_written_truth(row, snap):
    record = _record(row)
    actual = record_containment(
        record, row["ecosystem"], row["name"], row["version"]
    ).contained
    assert actual == row["expected_contained"], (
        f"ORACLE DISAGREES WITH HAND-DERIVED TRUTH\n"
        f"  {row['advisory_id']} {row['ecosystem']}/{row['name']} @ {row['version']}\n"
        f"  expected contained={row['expected_contained']}, oracle said {actual}\n"
        f"  reasoning: {row['human_rationale']}"
    )


def test_table_is_boundary_weighted():
    """A truth table of easy interior cases would pass a flipped oracle. At least half
    the rows must sit on an interval boundary."""
    boundary = [r for r in ROWS if "BOUNDARY" in r["human_rationale"]]
    assert len(boundary) >= len(ROWS) // 2, (
        f"only {len(boundary)}/{len(ROWS)} rows are boundary cases — a sign flip could "
        "slip through"
    )


def test_table_covers_both_upper_bound_kinds_and_both_ecosystems():
    """`fixed` (exclusive) and `last_affected` (inclusive) are opposite conventions;
    a flip in either direction must be caught, on both scoring tiers."""
    rationales = " ".join(r["human_rationale"] for r in ROWS)
    assert "last_affected" in rationales and "fixed" in rationales
    assert "GAP" in rationales, "no multi-range gap case — OR-aggregation is untested"
    assert "PRERELEASE" in rationales, "no prerelease boundary case"
    ecosystems = {r["ecosystem"] for r in ROWS}
    assert {"npm", "PyPI"} <= ecosystems


def test_every_row_carries_its_reasoning():
    for r in ROWS:
        assert r["human_rationale"].strip(), f"{r['advisory_id']} has no rationale"
        assert isinstance(r["expected_contained"], bool)
