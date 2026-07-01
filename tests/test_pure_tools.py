"""The three PURE tools (DECISIONS.md §2.4 tools 1, 3, 5) on the uniform envelope (§2.1).

Every failure is an envelope error — tools never throw. `check_version_affected`
computes RAW containment only (the withdrawn override lives at the verdict layer);
`compute_minimal_fix` short-circuits on withdrawn records (v1.1.0).
"""

import copy
import json

import pytest

from depguard.tools.pure import (
    check_version_affected,
    compute_minimal_fix,
    parse_manifest,
)

SNAP = "depguard-corpus-2026-07-02-0123456789ab"


def make_record(**overrides):
    """A minimal §2.3 OSVRecord: npm lodash, SEMVER [0, 4.17.21)."""
    record = {
        "id": "GHSA-35jh-r3h4-6jhm",
        "modified": "2021-03-19T00:00:00Z",
        "withdrawn": None,
        "aliases": ["CVE-2021-23337"],
        "summary": "Command injection in lodash",
        "affected": [
            {
                "package": {"ecosystem": "npm", "name": "lodash", "purl": None},
                "ranges": [
                    {
                        "type": "SEMVER",
                        "events": [{"introduced": "0"}, {"fixed": "4.17.21"}],
                    }
                ],
                "versions": [],
                "scoring_tier": "membership_and_minfix",
            }
        ],
        "references": [],
        "database_specific": None,
    }
    record.update(overrides)
    return record


def assert_ok(env):
    assert env["ok"] is True, f"expected ok envelope, got error: {env['error']}"
    assert env["error"] is None
    assert env["data"]["source_meta"]["source"] == "local"
    assert env["data"]["source_meta"]["corpus_snapshot_id"] == SNAP
    return env["data"]


def assert_err(env, code):
    assert env["ok"] is False, f"expected error envelope, got data: {env['data']}"
    assert env["data"] is None
    assert env["error"]["code"] == code
    assert env["error"]["retryable"] is False  # always false in corpus mode (§2.1)
    return env["error"]


# =====================================================================
# Tool 1: parse_manifest
# =====================================================================

PACKAGE_JSON = json.dumps(
    {
        "name": "demo-app",
        "dependencies": {
            "lodash": "4.17.20",
            "@scoped/pkg": "1.0.0",
            "express": "^4.18.0",
            "left-pad": "~1.3.0",
            "react": ">=17.0.0 <19",
            "weird": "*",
            "gitdep": "git+https://github.com/x/y.git",
        },
        "devDependencies": {"jest": "29.0.0"},
    }
)


def deps_by_name(data):
    return {d["name"]: d for d in data["dependencies"]}


def test_parse_manifest_npm_exact_pins():
    data = assert_ok(
        parse_manifest("npm", "package.json", PACKAGE_JSON, corpus_snapshot_id=SNAP)
    )
    deps = deps_by_name(data)
    assert deps["lodash"] == {
        "ecosystem": "npm", "name": "lodash", "version": "4.17.20", "pinned": True
    }
    assert deps["@scoped/pkg"]["pinned"] is True  # scoped names kept verbatim
    assert deps["jest"]["pinned"] is True  # devDependencies included


def test_parse_manifest_npm_ranges_are_unpinned_best_effort():
    data = assert_ok(
        parse_manifest("npm", "package.json", PACKAGE_JSON, corpus_snapshot_id=SNAP)
    )
    deps = deps_by_name(data)
    assert deps["express"] == {
        "ecosystem": "npm", "name": "express", "version": "4.18.0", "pinned": False
    }
    assert deps["left-pad"]["version"] == "1.3.0" and deps["left-pad"]["pinned"] is False
    assert deps["react"]["version"] == "17.0.0" and deps["react"]["pinned"] is False


def test_parse_manifest_npm_unparseable_specs_reported_not_dropped():
    data = assert_ok(
        parse_manifest("npm", "package.json", PACKAGE_JSON, corpus_snapshot_id=SNAP)
    )
    deps = deps_by_name(data)
    assert "weird" not in deps and "gitdep" not in deps
    assert any("weird" in line for line in data["unparsed_lines"])
    assert any("gitdep" in line for line in data["unparsed_lines"])


def test_parse_manifest_pypi_flat_json_with_pep503_normalization():
    text = json.dumps({"Requests": "2.31.0", "typing_extensions": "4.8.0"})
    data = assert_ok(
        parse_manifest("PyPI", "deps.json", text, corpus_snapshot_id=SNAP)
    )
    deps = deps_by_name(data)
    # PEP503: lowercase, runs of -_. collapse to -
    assert "requests" in deps and deps["requests"]["pinned"] is True
    assert "typing-extensions" in deps


def test_parse_manifest_bad_inputs():
    assert_err(
        parse_manifest("Maven", "pom.xml", "<xml/>", corpus_snapshot_id=SNAP),
        "BAD_INPUT",
    )
    assert_err(
        parse_manifest("npm", "package.json", "   ", corpus_snapshot_id=SNAP),
        "BAD_INPUT",
    )
    assert_err(
        parse_manifest("npm", "package.json", "{not json", corpus_snapshot_id=SNAP),
        "BAD_INPUT",
    )
    # crates.io/Go are corpus ecosystems but v0.1 ships no parser for them
    assert_err(
        parse_manifest("Go", "go.mod", "module x", corpus_snapshot_id=SNAP),
        "BAD_INPUT",
    )


# =====================================================================
# Tool 3: check_version_affected — RAW containment only
# =====================================================================

def check(version, record=None, ecosystem="npm", name="lodash"):
    return check_version_affected(
        ecosystem, name, version, record or make_record(), corpus_snapshot_id=SNAP
    )


def test_contained_inside_range_with_citation():
    data = assert_ok(check("4.17.20"))
    assert data["contained"] is True
    assert data["matched_by"] == "semver_range"
    assert data["matched_range"] == {
        "introduced": "0", "fixed": "4.17.21", "last_affected": None
    }
    assert data["withdrawn_timestamp"] is None


def test_fixed_bound_is_exclusive():
    assert assert_ok(check("4.17.21"))["contained"] is False
    assert assert_ok(check("4.17.22"))["contained"] is False


def test_introduced_zero_means_negative_infinity():
    assert assert_ok(check("0.0.1"))["contained"] is True


def test_last_affected_bound_is_inclusive():
    record = make_record()
    record["affected"][0]["ranges"][0]["events"] = [
        {"introduced": "1.0.0"}, {"last_affected": "1.2.3"}
    ]
    assert assert_ok(check("1.2.3", record))["contained"] is True
    assert assert_ok(check("1.2.4", record))["contained"] is False
    assert assert_ok(check("0.9.0", record))["contained"] is False


def test_open_ended_range_when_no_close_event():
    record = make_record()
    record["affected"][0]["ranges"][0]["events"] = [{"introduced": "2.0.0"}]
    assert assert_ok(check("99.0.0", record))["contained"] is True
    assert assert_ok(check("1.9.9", record))["contained"] is False


def test_versions_list_membership_by_comparator_equality():
    record = make_record()
    record["affected"][0]["ranges"] = []
    record["affected"][0]["versions"] = ["1.0.0", "1.0.1"]
    data = assert_ok(check("1.0.1", record))
    assert data["contained"] is True
    assert data["matched_by"] == "versions_list"
    assert data["matched_range"] is None
    assert assert_ok(check("1.0.2", record))["contained"] is False


def test_e_a_selects_matching_ecosystem_and_name_only():
    record = make_record()
    # add a PyPI entry with a range that WOULD contain the version
    record["affected"].append(
        {
            "package": {"ecosystem": "PyPI", "name": "lodash", "purl": None},
            "ranges": [
                {"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "99.0.0"}]}
            ],
            "versions": [],
            "scoring_tier": "membership_only",
        }
    )
    # npm query at 4.17.21 (outside npm range, inside the PyPI one) must NOT match
    assert assert_ok(check("4.17.21", record))["contained"] is False


def test_multi_entry_or_aggregation_cites_first_matching_entry():
    record = make_record()
    record["affected"].append(
        {
            "package": {"ecosystem": "npm", "name": "lodash", "purl": None},
            "ranges": [
                {"type": "SEMVER", "events": [{"introduced": "5.0.0"}, {"fixed": "5.0.2"}]}
            ],
            "versions": [],
            "scoring_tier": "membership_and_minfix",
        }
    )
    data = assert_ok(check("5.0.1", record))  # only the SECOND entry contains it
    assert data["contained"] is True
    assert data["matched_range"]["introduced"] == "5.0.0"


def test_ecosystem_range_entries_abstain_without_failing():
    record = make_record()
    record["affected"].append(
        {
            "package": {"ecosystem": "npm", "name": "lodash", "purl": None},
            "ranges": [
                {"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}
            ],
            "versions": [],
            "scoring_tier": "membership_only",
        }
    )
    # decidable entry still decides; ECOSYSTEM entry abstains (§2.4 step 3)
    assert assert_ok(check("4.17.20", record))["contained"] is True


def test_empty_e_a_is_contained_false_not_error():
    data = assert_ok(check("1.0.0", name="not-in-record"))
    assert data["contained"] is False
    assert data["matched_by"] is None


def test_all_entries_undecidable_is_range_unresolvable():
    record = make_record()
    record["affected"][0]["ranges"] = [{"type": "GIT", "events": [{"introduced": "abc123"}]}]
    record["affected"][0]["versions"] = []
    assert_err(check("1.0.0", record), "RANGE_UNRESOLVABLE")


def test_withdrawn_timestamp_surfaced_but_containment_stays_raw():
    record = make_record(withdrawn="2024-01-01T00:00:00Z")
    data = assert_ok(check("4.17.20", record))
    assert data["contained"] is True  # RAW — the override lives at the verdict layer
    assert data["withdrawn_timestamp"] == "2024-01-01T00:00:00Z"


def test_unparseable_input_version_is_bad_input():
    assert_err(check("not-a-version"), "BAD_INPUT")


# =====================================================================
# Tool 5: compute_minimal_fix
# =====================================================================

PUBLISHED = ["4.17.19", "4.17.20", "4.17.21", "4.17.22"]


def minfix(current, record=None, published=None, ecosystem="npm", name="lodash"):
    return compute_minimal_fix(
        ecosystem, name, current, record or make_record(),
        published if published is not None else PUBLISHED,
        corpus_snapshot_id=SNAP,
    )


def test_withdrawn_short_circuit_never_chases_ghost_fixes():
    record = make_record(withdrawn="2024-01-01T00:00:00Z")
    data = assert_ok(minfix("4.17.20", record))
    assert data == {
        "minimal_fixed_version": None,
        "reason": "withdrawn_non_actionable",
        "candidates_considered": [],
        "source_meta": data["source_meta"],
    }


def test_published_version_clears():
    data = assert_ok(minfix("4.17.20"))
    assert data["minimal_fixed_version"] == "4.17.21"
    assert data["reason"] == "published_version_clears"
    assert data["candidates_considered"] == ["4.17.20", "4.17.21"]


def test_fix_must_be_actually_published():
    # range says fixed at 4.17.21, but that release never shipped
    data = assert_ok(minfix("4.17.20", published=["4.17.19", "4.17.20"]))
    assert data["minimal_fixed_version"] is None
    assert data["reason"] == "no_fix_available"


def test_already_safe_matches_p2_gold_formula():
    # current 4.17.22 is not contained; smallest published >= current that is
    # not contained is 4.17.22 itself — tool must equal P2 gold exactly (§5)
    data = assert_ok(minfix("4.17.22"))
    assert data["reason"] == "already_safe"
    assert data["minimal_fixed_version"] == "4.17.22"


def test_minimal_fix_orders_published_versions_numerically():
    published = ["4.17.20", "4.17.100", "4.17.21"]
    data = assert_ok(minfix("4.17.20", published=published))
    assert data["minimal_fixed_version"] == "4.17.21"  # not 4.17.100 first


def test_minimal_fix_bad_current_version():
    assert_err(minfix("garbage"), "BAD_INPUT")
