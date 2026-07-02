"""D6 — the ~10-case golden set is internally consistent and verifier-CORRECT.

Every seed's deterministic-arm trajectory must (1) validate against §3, (2) be
scored CORRECT by the §5 verifier, and (3) reproduce the committed golden artifacts
byte-for-byte. Also asserts the §4.2 category coverage the golden set exists to
provide (true/false positive, withdrawn, no-fix, already-safe, multi-affected,
single_source) is actually present.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from depguard.agreement import observe_from_extract  # noqa: E402
from depguard.graph import build_gold, run_graph  # noqa: E402
from depguard.snapshot import Snapshot  # noqa: E402
from depguard.tools.external import (  # noqa: E402
    osv_query_package,
    resolve_published_versions,
)
from depguard.verifier import verify_verdict  # noqa: E402
from golden.seeds import SEED_INPUTS  # noqa: E402

SNAP = Snapshot()
GOLD_T = REPO / "golden" / "trajectories"
GOLD_E = REPO / "golden" / "expected"


def _score(verdict, alert):
    eco, name, ver = alert["ecosystem"], alert["name"], alert["pinned_version"]
    advisories = osv_query_package(eco, name, ver, snapshot=SNAP)["data"]["advisories"]
    record = next(
        r for r in advisories
        if r["id"] == alert["advisory_id"] or alert["advisory_id"] in r.get("aliases", [])
    )
    pub = resolve_published_versions(eco, name, snapshot=SNAP)["data"]["versions"]
    obs = observe_from_extract(SNAP.read_extract(eco, name), ver)
    return verify_verdict(
        verdict, ecosystem=eco, name=name, pinned_version=ver,
        osv_record=record, published_versions=pub, depsdev=obs,
    )


@pytest.mark.parametrize("seed", sorted(SEED_INPUTS))
def test_every_seed_is_scored_correct(seed):
    inp = SEED_INPUTS[seed]
    traj = run_graph(inp, SNAP, system_variant="deterministic_script")
    by_alert = {a["alert_id"]: a for a in inp["alerts"]}
    assert traj["verdicts"], f"{seed} produced no verdicts"
    for v in traj["verdicts"]:
        s = _score(v, by_alert[v["alert_id"]])
        assert s.status == "scored"
        assert s.correct is True, f"{seed} verdict not correct: {s.predicates}"


@pytest.mark.parametrize("seed", sorted(SEED_INPUTS))
def test_committed_artifacts_match_fresh_run(seed):
    inp = SEED_INPUTS[seed]
    traj = run_graph(inp, SNAP, system_variant="deterministic_script")
    committed = json.loads((GOLD_T / f"{seed}.jsonl").read_text())
    assert traj == committed, f"{seed}: regenerate with scripts/gen_golden.py"
    assert build_gold(inp, SNAP) == json.loads((GOLD_E / f"{seed}.jsonl").read_text())


def test_category_coverage_across_the_golden_set():
    """The golden set covers the §4.2 branch categories (mechanically detected)."""
    seen = {"tp": False, "fp": False, "withdrawn": False, "no_fix": False,
            "already_safe": False, "multi_affected": False, "single_source": False}
    for inp in SEED_INPUTS.values():
        traj = run_graph(inp, SNAP, system_variant="deterministic_script")
        for v in traj["verdicts"]:
            if v["affected"]:
                seen["tp"] = True
            else:
                seen["fp"] = True
            if v["withdrawn"]:
                seen["withdrawn"] = True
            if v["source_agreement"] == "single_source":
                seen["single_source"] = True
            if v["affected"] and v["minimal_fixed_version"] is None:
                seen["no_fix"] = True
            if (not v["affected"]) and v["minimal_fixed_version"] == \
                    inp["alerts"][0]["pinned_version"]:
                seen["already_safe"] = True
        # multi-affected: the cited OSV record has >= 2 affected entries
        for e in traj["evidence"]:
            if e["source"] == "osv":
                rec = json.loads(
                    (SNAP.corpus_dir / "osv" / e["affected_package"]["ecosystem"]
                     / f"{e['advisory_id']}.json").read_text()
                )
                if len(rec.get("affected", [])) >= 2:
                    seen["multi_affected"] = True
    missing = [k for k, v in seen.items() if not v]
    assert not missing, f"golden set missing categories: {missing}"
