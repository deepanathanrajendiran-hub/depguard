"""Consistency tests for the normative schema registries (DECISIONS.md §0).

These tests are the enforcement mechanism for house rule 3: naming drift between the
registries, the tools, the golden set, and the metrics must fail CI, never mis-score silently.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

SCHEMAS = Path(__file__).parent.parent / "schemas"

# DECISIONS.md §0.1 — the ONLY legal tool_name values
CANONICAL_TOOL_NAMES = {
    "parse_manifest",
    "osv_query_package",
    "check_version_affected",
    "resolve_published_versions",
    "compute_minimal_fix",
    "crosscheck_second_source",
}

# DECISIONS.md §0.2 — the ONLY legal PlanAction values
CANONICAL_PLAN_ACTIONS = {
    "plan",
    "parse_manifest",
    "retrieve_advisory",
    "resolve_versions",
    "check_containment",
    "compute_minimal_fixed",
    "cross_check_source",
    "emit_verdict",
}

CORPUS_ECOSYSTEMS = {"npm", "PyPI", "crates.io", "Go"}       # §1.2 / §0.4 (v1.3.0)
MINFIX_ECOSYSTEMS = {"npm", "crates.io", "Go"}               # §1.2 strict allowlist


def load(name: str):
    with open(SCHEMAS / name) as f:
        return json.load(f)


# ---------- registry consistency ----------

def test_all_registry_files_parse():
    for name in (
        "ecosystem_system_map.json",
        "plan_action_tool_map.json",
        "tool_key_args.json",
        "trajectory.schema.json",
    ):
        assert load(name), f"{name} is empty or failed to parse"


def test_tool_key_args_covers_exactly_the_canonical_tools():
    keys = set(load("tool_key_args.json").keys())
    assert keys == CANONICAL_TOOL_NAMES


def test_plan_action_map_matches_canonical_alphabets():
    m = load("plan_action_tool_map.json")
    assert set(m["tool_names"]) == CANONICAL_TOOL_NAMES
    assert set(m["actions"].keys()) == CANONICAL_PLAN_ACTIONS
    # every non-control action maps to exactly one canonical tool; controls map to null
    mapped = {a["tool_name"] for a in m["actions"].values() if a["tool_name"] is not None}
    assert mapped == CANONICAL_TOOL_NAMES
    assert m["actions"]["plan"]["tool_name"] is None
    assert m["actions"]["emit_verdict"]["tool_name"] is None


def test_ecosystem_map_corpus_and_tiers():
    m = load("ecosystem_system_map.json")
    assert set(m["corpus_ecosystems"]) == CORPUS_ECOSYSTEMS
    assert set(m["minfix_ecosystems"]) == MINFIX_ECOSYSTEMS
    in_corpus = {k for k, v in m["ecosystems"].items() if v["in_corpus"]}
    assert in_corpus == CORPUS_ECOSYSTEMS
    minfix = {
        k for k, v in m["ecosystems"].items()
        if v.get("scoring_tier") == "membership_and_minfix"
    }
    assert minfix == MINFIX_ECOSYSTEMS
    # PyPI is ALWAYS membership_only (§1.2); excluded ecosystems have no comparator
    assert m["ecosystems"]["PyPI"]["scoring_tier"] == "membership_only"
    for eco in ("Maven", "RubyGems", "NuGet"):
        assert m["ecosystems"][eco]["in_corpus"] is False
        assert m["ecosystems"][eco]["comparator"] is None
        assert m["ecosystems"][eco]["excluded_reason"] == "NO_VETTED_COMPARATOR"


def test_trajectory_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(load("trajectory.schema.json"))


def test_trajectory_schema_enums_match_registries():
    s = load("trajectory.schema.json")
    assert set(s["$defs"]["toolName"]["enum"]) == CANONICAL_TOOL_NAMES
    assert set(s["$defs"]["planAction"]["enum"]) == CANONICAL_PLAN_ACTIONS
    assert set(s["$defs"]["ecosystem"]["enum"]) == CORPUS_ECOSYSTEMS


# ---------- trajectory instance validation ----------

SNAP = "depguard-corpus-2026-07-01-0123456789ab"

VALID_TRAJECTORY = {
    "schema_version": "1.0.0",
    "trajectory_id": "traj-0001",
    "created_at": "2026-07-01T12:00:00Z",
    "system_variant": "multi_agent",
    "model_route": "sonnet",
    "corpus_snapshot_id": SNAP,
    "gold_ref": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "otel": {"trace_id": "0af7651916cd43dd8448eb211c80319c", "root_span_id": "b7ad6b7169203331"},
    "input": {
        "manifest": [
            {"ecosystem": "npm", "name": "lodash", "pinned_version": "4.17.20", "purl": None}
        ],
        "alerts": [
            {
                "alert_id": "a1",
                "ecosystem": "npm",
                "name": "lodash",
                "pinned_version": "4.17.20",
                "advisory_id": "GHSA-35jh-r3h4-6jhm",
                "source": "scanner",
            }
        ],
    },
    "plan": [
        {
            "step_index": 0,
            "action": "plan",
            "alert_id": None,
            "rationale": "plan the triage run",
            "status": "executed",
            "produced_verdict_for": None,
        },
        {
            "step_index": 1,
            "action": "check_containment",
            "alert_id": "a1",
            "rationale": "is 4.17.20 inside the affected range?",
            "status": "executed",
            "produced_verdict_for": None,
        },
        {
            "step_index": 2,
            "action": "emit_verdict",
            "alert_id": "a1",
            "rationale": "emit verdict for a1",
            "status": "executed",
            "produced_verdict_for": "a1",
        },
    ],
    "tool_calls": [
        {
            "tool_call_id": "tc1",
            "span_id": "s1",
            "parent_span_id": "s0",
            "agent": "tool_worker",
            "tool_name": "check_version_affected",
            "tool_type": "function",
            "arguments": {"ecosystem": "npm", "name": "lodash", "version": "4.17.20"},
            "result": {
                "ok": True,
                "data": {
                    "contained": True,
                    "matched_by": "semver_range",
                    "withdrawn_timestamp": None,
                    "source_meta": {
                        "source": "local",
                        "corpus_snapshot_id": SNAP,
                        "license": "CC0-1.0",
                        "source_url": None,
                    },
                },
                "error": None,
            },
            "status": "ok",
            "started_at": "2026-07-01T12:00:01Z",
            "ended_at": "2026-07-01T12:00:02Z",
            "source": "local",
            "corpus_snapshot_id": SNAP,
        }
    ],
    "evidence": [
        {
            "evidence_id": "e1",
            "alert_id": "a1",
            "tool_call_id": "tc1",
            "source": "osv",
            "advisory_id": "GHSA-35jh-r3h4-6jhm",
            "withdrawn": None,
            "affected_package": {"ecosystem": "npm", "name": "lodash"},
            "range_type": "SEMVER",
            "range_events": [{"introduced": "0"}, {"fixed": "4.17.21"}],
            "enumerated_versions": None,
            "references": [
                {"type": "ADVISORY", "url": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm"}
            ],
            "license": "CC-BY-4.0",
            "attribution_url": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm",
            "corpus_snapshot_id": SNAP,
        }
    ],
    "verdicts": [
        {
            "alert_id": "a1",
            "affected": True,
            "minimal_fixed_version": "4.17.21",
            "withdrawn": False,
            "cvss3_score": None,
            "evidence_ids": ["e1"],
            "source_agreement": "agree",
            "reconciliation_note": "",
        }
    ],
    "final_answer": {
        "verdicts_summary": {"n_alerts": 1, "n_true_positive": 1, "n_false_positive": 0,
                             "n_unresolved": 0},
        "per_alert": [],
        "emitted_at": "2026-07-01T12:00:05Z",
    },
}


@pytest.fixture()
def validator():
    return Draft202012Validator(load("trajectory.schema.json"))


def test_valid_trajectory_validates(validator):
    validator.validate(VALID_TRAJECTORY)


def test_deterministic_script_arm_is_legal(validator):
    t = copy.deepcopy(VALID_TRAJECTORY)
    t["system_variant"] = "deterministic_script"
    validator.validate(t)


def test_disagree_requires_nonempty_reconciliation_note(validator):
    t = copy.deepcopy(VALID_TRAJECTORY)
    t["verdicts"][0]["source_agreement"] = "disagree"
    t["verdicts"][0]["reconciliation_note"] = ""
    with pytest.raises(ValidationError):
        validator.validate(t)


def test_nonempty_note_forbidden_unless_disagree(validator):
    # §3.3: non-empty IFF disagree — enforced both directions
    t = copy.deepcopy(VALID_TRAJECTORY)
    t["verdicts"][0]["reconciliation_note"] = "unexpected note on an agree verdict"
    with pytest.raises(ValidationError):
        validator.validate(t)


def test_envelope_rejects_ok_true_with_error(validator):
    t = copy.deepcopy(VALID_TRAJECTORY)
    t["tool_calls"][0]["result"] = {
        "ok": True,
        "data": {"contained": True},
        "error": {"code": "BAD_INPUT", "message": "boom", "retryable": False},
    }
    with pytest.raises(ValidationError):
        validator.validate(t)


def test_range_event_must_carry_exactly_one_key(validator):
    t = copy.deepcopy(VALID_TRAJECTORY)
    t["evidence"][0]["range_events"] = [{"introduced": "0", "fixed": "4.17.21"}]
    with pytest.raises(ValidationError):
        validator.validate(t)


def test_unknown_tool_name_rejected(validator):
    t = copy.deepcopy(VALID_TRAJECTORY)
    t["tool_calls"][0]["tool_name"] = "semver_contains"  # discarded pre-§0.1 vocabulary
    with pytest.raises(ValidationError):
        validator.validate(t)


def test_excluded_ecosystem_rejected_in_manifest(validator):
    t = copy.deepcopy(VALID_TRAJECTORY)
    t["input"]["manifest"][0]["ecosystem"] = "Maven"  # CUT from corpus (v1.3.0)
    with pytest.raises(ValidationError):
        validator.validate(t)


def test_malformed_corpus_snapshot_id_rejected(validator):
    t = copy.deepcopy(VALID_TRAJECTORY)
    t["corpus_snapshot_id"] = "snapshot-1"  # pre-§0.5 naming drift
    with pytest.raises(ValidationError):
        validator.validate(t)
