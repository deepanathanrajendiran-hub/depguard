"""D6 — genuine branching seeds (DECISIONS.md §4.2): the graph must survive error
paths and emit a schema-valid trajectory whose tool_calls record the branch. These
give the trajectory metrics real variance (the whole point) rather than pinning at 1.0.
"""

import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from depguard.graph import run_graph  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _error_codes(traj):
    return [
        tc["result"]["error"]["code"]
        for tc in traj["tool_calls"]
        if not tc["result"]["ok"]
    ]


def test_unpinned_version_branches_to_bad_input():
    """A range spec instead of a pin (an unpinned manifest entry) is unparseable →
    check_version_affected returns BAD_INPUT; the trajectory stays schema-valid.

    BEHAVIOUR CHANGE (v1.1.0). This previously asserted `len(traj["verdicts"]) == 1`
    with the comment "retrieval still succeeded, so a verdict is still emitted
    (fallback, not affected)". That fallback was the most user-visible instance of the
    fail-unsafe bug: DepGuard reported a dependency as NOT AFFECTED when all it had
    actually established was that it could not parse `^4.17.0`. An unparseable pin is
    now an unresolved alert, matching the sibling SNAPSHOT_MALFORMED case below."""
    inp = {
        "manifest": [{"ecosystem": "npm", "name": "lodash",
                      "pinned_version": "^4.17.0", "purl": None}],
        "alerts": [{"alert_id": "unpinned-a1", "ecosystem": "npm", "name": "lodash",
                    "pinned_version": "^4.17.0", "advisory_id": "GHSA-35jh-r3h4-6jhm",
                    "source": "scanner"}],
    }
    traj = run_graph(inp, Snapshot(), system_variant="deterministic_script")  # validates on build
    assert "BAD_INPUT" in _error_codes(traj)
    assert traj["verdicts"] == [], "an unparseable pin must not yield a 'not affected' verdict"
    assert traj["final_answer"]["verdicts_summary"] == {
        "n_alerts": 1, "n_true_positive": 0, "n_false_positive": 0, "n_unresolved": 1,
    }


def test_corrupted_snapshot_branches_to_snapshot_malformed():
    """Running against a corpus with a corrupt OSV record surfaces SNAPSHOT_MALFORMED
    at retrieval; with nothing retrieved, no evidence-less verdict is emitted."""
    broken = Snapshot(FIXTURES / "broken_json_corpus")
    inp = {
        "manifest": [{"ecosystem": "npm", "name": "lodash",
                      "pinned_version": "4.17.20", "purl": None}],
        "alerts": [{"alert_id": "corrupt-a1", "ecosystem": "npm", "name": "lodash",
                    "pinned_version": "4.17.20", "advisory_id": "GHSA-35jh-r3h4-6jhm",
                    "source": "scanner"}],
    }
    traj = run_graph(inp, broken, system_variant="deterministic_script")
    assert "SNAPSHOT_MALFORMED" in _error_codes(traj)
    assert traj["verdicts"] == []  # nothing to verdict — the emit step was skipped
    assert any(s["action"] == "emit_verdict" and s["status"] == "skipped"
               for s in traj["plan"])
