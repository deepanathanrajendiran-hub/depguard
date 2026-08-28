"""The prose slice (§5.1, v1.2.0) — the slice where the deterministic script provably loses.

v0.1's headline was `deterministic_script ≡ multi_agent`, Δ = 0 with a [0,0] CI. That
tie was the CEILING before any code ran: the task was chosen to be mechanically decidable
so a shared-oracle verifier could exist, the script IS the reference implementation of
the label function, and the planner prompt enumerated the canonical plan verbatim. An
experiment whose best possible outcome is "no difference" carries no information.

This slice fixes the experiment rather than the framing. `redact_ranges` strips `ranges`
and `versions` from the frozen records, leaving the affected range only in the `details`
prose. `oracle.record_containment` then RAISES — asserted below — so the script's failure
is a raised exception, not a contested measurement. The verifier stays 100% mechanical:
P5 compares containment bitvectors over the frozen published list, running the SAME
`record_containment` on both the true record and the reconstruction.
"""

import json
from pathlib import Path

import pytest

from depguard.comparators import VersionParseError
from depguard.extractors import null_extractor, regex_extractor
from depguard.oracle import RangeUnresolvableError, record_containment, select_entries
from depguard.redact import (
    expand_events,
    gold_abstains,
    has_version_token,
    materialize_proposal,
    prose_of,
    redact_ranges,
)
from depguard.snapshot import Snapshot
from depguard.tools.external import resolve_published_versions
from depguard.verifier import verify_range_reconstruction

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus"
SNAP = Snapshot()


def _record(eco, aid):
    return json.loads((CORPUS / "osv" / eco / f"{aid}.json").read_text())


def _published(eco, name):
    r = resolve_published_versions(eco, name, snapshot=SNAP)
    return r["data"]["versions"] if r["ok"] else []


LODASH = ("npm", "GHSA-35jh-r3h4-6jhm", "lodash")
PYYAML = ("PyPI", "PYSEC-2020-176", "pyyaml")
DJANGO = ("PyPI", "GHSA-2gwj-7jmv-h26r", "django")


# ===================================================================== #
# Redaction is a pure, corpus-preserving transform
# ===================================================================== #

def test_redaction_never_mutates_the_input_or_the_corpus():
    eco, aid, _ = LODASH
    original = _record(eco, aid)
    before = json.dumps(original, sort_keys=True)
    redact_ranges(original)
    assert json.dumps(original, sort_keys=True) == before
    on_disk = (CORPUS / "osv" / eco / f"{aid}.json").read_text()
    assert json.loads(on_disk) == original


def test_redaction_is_deterministic():
    eco, aid, _ = LODASH
    a = redact_ranges(_record(eco, aid))
    b = redact_ranges(_record(eco, aid))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_redaction_keeps_identity_and_prose_drops_only_ranges():
    eco, aid, _ = LODASH
    red = redact_ranges(_record(eco, aid))
    assert red["id"] == aid
    assert red["details"] and red["summary"]
    for entry in red["affected"]:
        assert "ranges" not in entry
        assert entry["versions"] == []
        assert entry["package"]["name"]  # membership filter still works


def test_snapshot_id_is_unchanged_by_the_slice():
    """Redaction is a pure in-memory transform: it must never touch the corpus.

    Asserts the id still matches SNAPSHOT.lock rather than a literal. The literal was
    wrong to pin here — it made this test fail when the corpus was legitimately re-frozen
    to add crates.io and Go, which is a snapshot change the slice had nothing to do with.
    What the slice must guarantee is that IT changes nothing, which is what this checks."""
    from depguard.corpus_snapshot import compute_snapshot_id, load_snapshot_lock

    lock = load_snapshot_lock(CORPUS)
    before = SNAP.snapshot_id
    assert before == lock["corpus_snapshot_id"]
    for path in sorted((CORPUS / "osv").rglob("*.json"))[:5]:
        redact_ranges(json.loads(path.read_text()))
    assert compute_snapshot_id(
        CORPUS, lock["capture_date"], lock["curation_ruleset_version"]
    ) == before, "redaction mutated the corpus on disk"


# ===================================================================== #
# THE LOAD-BEARING CLAIM: the script provably cannot decide a redacted record
# ===================================================================== #

@pytest.mark.parametrize("eco,aid,name,version", [
    (*LODASH, "4.17.20"),
    (*PYYAML, "5.1.2"),
    (*DJANGO, "2.2.27"),
])
def test_script_arm_cannot_decide_redacted(eco, aid, name, version):
    """Not "scores poorly" — RAISES. The membership filter still matches entries, so
    this is a genuine undecidability, not an empty-E_A exclusion."""
    red = redact_ranges(_record(eco, aid))
    assert select_entries(red, eco, name), "membership filter must still match"
    with pytest.raises(RangeUnresolvableError):
        record_containment(red, eco, name, version)


def test_the_unredacted_record_decides_the_same_case_fine():
    """Guards the test above: the redaction is what breaks it, not the fixture."""
    eco, aid, name = LODASH
    assert record_containment(_record(eco, aid), eco, name, "4.17.20").contained is True


# ===================================================================== #
# P5 scores BEHAVIOUR, not text
# ===================================================================== #

def _score(proposal, key=LODASH):
    eco, aid, name = key
    return verify_range_reconstruction(
        proposal, ecosystem=eco, name=name, true_record=_record(eco, aid),
        published_versions=_published(eco, name),
    )


def test_exact_reconstruction_passes():
    r = _score({"events": [{"introduced": "0"}, {"fixed": "4.17.21"}],
                "versions": [], "abstain": False})
    assert r.passed is True and r.n_mismatch == 0


def test_textually_different_but_semantically_identical_passes():
    """`last_affected: 4.17.20` and `fixed: 4.17.21` denote the same set of REAL
    releases. Scoring text would call this wrong; scoring behaviour calls it right."""
    r = _score({"events": [{"introduced": "0"}, {"last_affected": "4.17.20"}],
                "versions": [], "abstain": False})
    assert r.passed is True


def test_off_by_one_fails_and_names_the_version():
    r = _score({"events": [{"introduced": "0"}, {"fixed": "4.17.22"}],
                "versions": [], "abstain": False})
    assert r.passed is False
    assert r.n_mismatch == 1
    assert r.mismatches[0][0] == "4.17.21"


def test_abstaining_on_a_decidable_record_is_a_miss():
    assert _score({"events": [], "versions": [], "abstain": True}).passed is False


def test_inventing_a_range_on_an_abstain_record_is_a_miss():
    """The asymmetry that stops an extractor farming the metric by always guessing."""
    abstainers = [
        (p.parent.name, json.loads(p.read_text()))
        for p in sorted((CORPUS / "osv").rglob("*.json"))
        if gold_abstains(json.loads(p.read_text()))
    ]
    assert abstainers, "corpus has no gold-abstain record — the asymmetry is untested"
    eco, rec = abstainers[0]
    name = rec["affected"][0]["package"]["name"]
    r = verify_range_reconstruction(
        {"events": [{"introduced": "0"}, {"fixed": "99.0.0"}], "versions": [],
         "abstain": False},
        ecosystem=eco, name=name, true_record=rec,
        published_versions=_published(eco, name),
    )
    assert r.passed is False


def test_abstaining_on_an_abstain_record_is_correct():
    eco, rec = next(
        (p.parent.name, json.loads(p.read_text()))
        for p in sorted((CORPUS / "osv").rglob("*.json"))
        if gold_abstains(json.loads(p.read_text()))
    )
    name = rec["affected"][0]["package"]["name"]
    r = verify_range_reconstruction(
        None, ecosystem=eco, name=name, true_record=rec,
        published_versions=_published(eco, name),
    )
    assert r.passed is True


def test_gold_abstain_is_mechanically_determined():
    """No human judgement in the label: a record abstains iff its prose has no version
    token. Byte-reproducible from frozen bytes."""
    eco, aid, _ = LODASH
    rec = _record(eco, aid)
    assert has_version_token(prose_of(rec))
    assert gold_abstains(rec) is False


# ===================================================================== #
# Materialisation
# ===================================================================== #

def test_expand_events_applies_osv_interval_semantics():
    pub = ["1.0.0", "1.5.0", "2.0.0", "2.5.0", "3.0.0"]
    covered = expand_events([{"introduced": "1.0.0"}, {"fixed": "2.0.0"}], pub, "npm")
    assert covered == ["1.0.0", "1.5.0"]  # fixed is EXCLUSIVE
    covered = expand_events([{"introduced": "1.0.0"}, {"last_affected": "2.0.0"}], pub, "npm")
    assert covered == ["1.0.0", "1.5.0", "2.0.0"]  # last_affected is INCLUSIVE


def test_expand_events_ors_sibling_intervals_and_leaves_gaps():
    pub = ["1.0.0", "1.5.0", "2.0.0", "2.5.0", "3.0.0", "3.5.0"]
    covered = expand_events(
        [{"introduced": "1.0.0"}, {"fixed": "1.5.0"},
         {"introduced": "3.0.0"}, {"fixed": "3.5.0"}], pub, "npm")
    assert covered == ["1.0.0", "3.0.0"]


def test_malformed_events_do_not_crash_the_arm():
    pub = ["1.0.0", "2.0.0"]
    assert expand_events([{"bogus": "x"}, "not-a-dict", {}], pub, "npm") == []
    assert expand_events([{"introduced": "not-a-version"}, {"fixed": "2.0.0"}], pub, "npm") == []


def test_materialisation_clamps_claims_to_the_published_list():
    eco, aid, name = LODASH
    out = materialize_proposal(
        _record(eco, aid),
        {"events": [], "versions": ["4.17.20", "99.99.99"], "abstain": False},
        ecosystem=eco, name=name, published=_published(eco, name),
    )
    versions = out["affected"][0]["versions"]
    assert "4.17.20" in versions and "99.99.99" not in versions


# ===================================================================== #
# The two non-LLM arms, measured
# ===================================================================== #

def _corpus_pairs():
    pairs = []
    for path in sorted((CORPUS / "osv").rglob("*.json")):
        rec = json.loads(path.read_text())
        eco = path.parent.name
        for entry in rec.get("affected", []):
            if entry["package"]["ecosystem"] != eco:
                continue
            name = entry["package"]["name"]
            pub = _published(eco, name)
            if pub:
                pairs.append((rec, eco, name, pub))
            break
    return pairs


def _measure(extractor):
    correct = scored = 0
    for rec, eco, name, pub in _corpus_pairs():
        r = verify_range_reconstruction(
            extractor(prose_of(rec), pub, eco), ecosystem=eco, name=name,
            true_record=rec, published_versions=pub,
        )
        if r.status == "excluded":
            continue
        scored += 1
        correct += bool(r.passed)
    return correct, scored


def test_null_extractor_only_gets_the_abstain_records():
    """The script arm's score IS the gold-abstain count — it is 0 on every record the
    prose actually describes. This is the number that makes the tie impossible."""
    correct, scored = _measure(null_extractor)
    n_abstain = sum(1 for rec, _, _, _ in _corpus_pairs() if gold_abstains(rec))
    assert correct == n_abstain
    assert correct < scored, "the script must not be able to score everything"


def test_regex_baseline_is_a_real_baseline_not_a_straw_man():
    """It must clearly beat abstaining, or the LLM comparison is against nothing."""
    regex_correct, scored = _measure(regex_extractor)
    null_correct, _ = _measure(null_extractor)
    assert regex_correct > null_correct * 2
    assert regex_correct / scored >= 0.3


def test_regex_handles_the_interleaved_branch_form():
    """"Django 2.2 before 2.2.28, 3.2 before 3.2.13, and 4.0 before 4.0.4" — three
    interleaved intervals. A baseline that fluffed this would be a straw man."""
    eco, aid, name = DJANGO
    rec = _record(eco, aid)
    r = verify_range_reconstruction(
        regex_extractor(prose_of(rec), _published(eco, name), eco),
        ecosystem=eco, name=name, true_record=rec,
        published_versions=_published(eco, name),
    )
    assert r.passed is True


def test_extractors_never_raise_on_any_corpus_record():
    for rec, eco, name, pub in _corpus_pairs():
        for extractor in (null_extractor, regex_extractor):
            out = extractor(prose_of(rec), pub, eco)
            assert set(out) == {"events", "versions", "abstain"}


# ===================================================================== #
# The same fail-unsafe class as the tp_axios bug, in the graph this time
# ===================================================================== #

def _redacted_corpus(tmp_path, eco, aid, name):
    """A real corpus with ONE record redacted, so check_version_affected returns a
    RANGE_UNRESOLVABLE error envelope on it."""
    import shutil
    dst = tmp_path / "corpus"
    shutil.copytree(CORPUS, dst)
    target = dst / "osv" / eco / f"{aid}.json"
    target.write_text(json.dumps(redact_ranges(json.loads(target.read_text())), indent=1))
    return Snapshot(dst)


def test_unresolvable_range_is_not_silently_reported_as_not_affected(tmp_path):
    """`_exec_check` did `data = result["data"] if result["ok"] else {}` and then
    `pa["contained"] = bool(data.get("contained"))`, so an ERROR envelope became
    `contained=False` — the arm answered "not affected" about a package whose range it
    could not resolve. Same fail-unsafe class as the tp_axios summary: absence of an
    answer became an all-clear. An undecidable alert must yield NO verdict."""
    from depguard.graph import run_graph
    from golden.seeds import SEED_INPUTS

    eco, aid, name = LODASH
    snap = _redacted_corpus(tmp_path, eco, aid, name)
    inp = SEED_INPUTS["tp_lodash"]
    assert inp["alerts"][0]["advisory_id"] == aid

    traj = run_graph(inp, snap, system_variant="deterministic_script")
    dismissals = [v for v in traj["verdicts"] if v["affected"] is False]
    assert not dismissals, (
        "an unresolvable range was reported as 'not affected': "
        f"{[v['alert_id'] for v in dismissals]}"
    )
    summary = traj["final_answer"]["verdicts_summary"]
    assert summary["n_false_positive"] == 0
    assert summary["n_unresolved"] == 1


def test_a_resolvable_record_still_produces_its_verdict(tmp_path):
    """Guards the fix from over-reaching: normal alerts must still be answered."""
    from depguard.graph import run_graph
    from golden.seeds import SEED_INPUTS

    traj = run_graph(SEED_INPUTS["tp_lodash"], SNAP, system_variant="deterministic_script")
    assert len(traj["verdicts"]) == 1
    assert traj["verdicts"][0]["affected"] is True
    assert traj["final_answer"]["verdicts_summary"]["n_unresolved"] == 0


def test_error_envelope_from_check_is_not_read_as_not_affected(tmp_path, monkeypatch):
    """The handler-level form of the same bug. `_exec_check` did
    `data = result["data"] if result["ok"] else {}` followed by
    `pa["contained"] = bool(data.get("contained"))`, so ANY error envelope became
    `contained=False` — a confident all-clear derived from an error.

    Corpus curation currently excludes the records that would reach this (ECOSYSTEM- and
    GIT-only entries are filtered before `_exec_check`), so the defect is latent rather
    than live today. It is fixed anyway: it is the same fail-unsafe class as the shipped
    tp_axios summary, and the prose slice adds a new caller that can produce exactly this
    envelope. The tool is stubbed here precisely because the corpus cannot reach it.
    """
    from depguard import graph as graph_mod
    from depguard.envelope import err
    from depguard.graph import run_graph
    from golden.seeds import SEED_INPUTS

    monkeypatch.setattr(
        graph_mod, "check_version_affected",
        lambda *a, **k: err("RANGE_UNRESOLVABLE", "every matching entry is undecidable"),
    )
    traj = run_graph(SEED_INPUTS["tp_lodash"], SNAP, system_variant="deterministic_script")

    dismissals = [v for v in traj["verdicts"] if v["affected"] is False]
    assert not dismissals, (
        "an unresolvable range was reported as 'not affected' — fail-unsafe: "
        f"{[v['alert_id'] for v in dismissals]}"
    )
    assert traj["final_answer"]["verdicts_summary"]["n_unresolved"] == 1
    assert traj["final_answer"]["verdicts_summary"]["n_false_positive"] == 0


def test_expand_events_matches_oracle_intervals_on_dangling_introduced():
    """P5 compares two runs of the same oracle, so a malformed proposal must expand
    exactly as those events would behave inside a real record. An `introduced` that is
    never closed — including one interrupted by the next `introduced` — runs to +inf in
    `oracle._intervals`, and must here too."""
    from depguard.oracle import _intervals

    pub = ["1.0.0", "1.5.0", "2.0.0", "2.5.0", "3.0.0"]
    events = [{"introduced": "1.0.0"}, {"introduced": "2.5.0"}, {"fixed": "3.0.0"}]

    intervals = [(lo, hi, inc) for lo, hi, inc, _ in _intervals(events)]
    assert ("1.0.0", None, False) in intervals, "guard: the oracle must open-end this"

    # 1.0.0 runs to +inf, so everything from 1.0.0 up is covered
    assert expand_events(events, pub, "npm") == pub


def test_expand_events_open_ended_trailing_interval():
    pub = ["1.0.0", "2.0.0", "3.0.0"]
    assert expand_events([{"introduced": "2.0.0"}], pub, "npm") == ["2.0.0", "3.0.0"]


# ===================================================================== #
# Extractor output parsing — a formatting choice must not be scored as a wrong answer
# ===================================================================== #

def test_llm_parser_accepts_paired_event_objects():
    """The model naturally emits `{"introduced": "0", "fixed": "4.3.6"}` — one object per
    interval — rather than OSV's strict one-key-per-event form. Observed live from
    deepseek-v4-flash on GHSA-24wv-mv5m-xv4h.

    The first parser required len(event) == 1 and dropped these, turning a CORRECT
    reconstruction into an empty proposal scored as wrong. That would have understated the
    LLM arm for a formatting preference, which is exactly the kind of silent
    measurement bug this repo exists to catch."""
    from depguard.llm_extractor import _normalize_events

    paired = [{"introduced": "0", "fixed": "4.3.6"},
              {"introduced": "4.4.0", "fixed": "4.4.3"}]
    assert _normalize_events(paired) == [
        {"introduced": "0"}, {"fixed": "4.3.6"},
        {"introduced": "4.4.0"}, {"fixed": "4.4.3"},
    ]


def test_llm_parser_still_accepts_strict_osv_form():
    from depguard.llm_extractor import _normalize_events

    strict = [{"introduced": "0"}, {"fixed": "4.3.6"}]
    assert _normalize_events(strict) == strict


def test_llm_parser_drops_unknown_keys_and_non_dicts():
    from depguard.llm_extractor import _normalize_events

    assert _normalize_events([{"bogus": "x"}, "nope", 7, {}]) == []
    assert _normalize_events([{"introduced": "1.0", "nonsense": "y"}]) == [{"introduced": "1.0"}]


def test_paired_form_scores_identically_to_strict_form():
    """End to end: the two spellings of the same range must reach the same P5 verdict."""
    from depguard.llm_extractor import _normalize_events

    eco, aid, name = LODASH
    strict = {"events": [{"introduced": "0"}, {"fixed": "4.17.21"}],
              "versions": [], "abstain": False}
    paired = {"events": _normalize_events([{"introduced": "0", "fixed": "4.17.21"}]),
              "versions": [], "abstain": False}
    assert _score(strict).passed is True
    assert _score(paired).passed is True


# ===================================================================== #
# Baseline grammar defects — a crippled control inflates the headline
# ===================================================================== #

def test_two_sided_through_is_inclusive():
    """"requests 2.1.0 through 2.5.3" INCLUDES 2.5.3. The first grammar put "through" in
    the same alternation as "before" and emitted `fixed: 2.5.3`, excluding it — so the
    control lost exactly the boundary version on both corpus seeds that use this form
    (requests 2.5.3, pyyaml 5.1.2), each failing with n_mismatch == 1.

    A baseline weakened by its own bug inflates the llm - regex delta, which is the
    headline. The one-sided `_THROUGH` pattern always had this right, so the module also
    contradicted itself."""
    out = regex_extractor("affects foo 2.1.0 through 2.5.3 only", [], "npm")
    assert {"last_affected": "2.5.3"} in out["events"]
    assert {"fixed": "2.5.3"} not in out["events"]
    assert {"introduced": "2.1.0"} in out["events"]


def test_two_sided_before_is_still_exclusive():
    out = regex_extractor("affects foo 2.2 before 2.2.28", [], "npm")
    assert {"fixed": "2.2.28"} in out["events"]
    assert {"last_affected": "2.2.28"} not in out["events"]


def test_grammar_reads_v_prefixed_versions():
    """"fixed in v1.27.0" must not read as "no version mentioned". `redact._VERSION_TOKEN`
    already fires inside `v1.27.0` (it matches the substring `27.0`), so gold labels such a
    seed DECIDABLE while the baseline abstained — the control was being scored against a
    token it could not see. 3 corpus seeds are affected (prismjs, node-forge, pillow)."""
    assert has_version_token("This bug has been fixed in v1.27.0.")
    out = regex_extractor("This bug has been fixed in v1.27.0.", [], "npm")
    assert out["abstain"] is False
    assert {"fixed": "1.27.0"} in out["events"], out["events"]


def test_v_prefix_does_not_leak_into_the_version_string():
    out = regex_extractor("all versions before v2.0.0 are affected", [], "npm")
    assert {"fixed": "2.0.0"} in out["events"]


@pytest.mark.parametrize("seed_eco,aid,name", [
    ("PyPI", "GHSA-pg2w-x9wp-vw92", "requests"),
    ("PyPI", "PYSEC-2020-176", "pyyaml"),
])
def test_through_seeds_now_pass_the_baseline(seed_eco, aid, name):
    """End to end on the two real corpus seeds the defect cost."""
    rec = _record(seed_eco, aid)
    pub = _published(seed_eco, name)
    r = verify_range_reconstruction(
        regex_extractor(prose_of(rec), pub, seed_eco),
        ecosystem=seed_eco, name=name, true_record=rec, published_versions=pub,
    )
    assert r.passed is True, f"{name}: {r.n_mismatch}/{r.n_versions} bits, {r.mismatches[:3]}"


def test_meter_is_thread_safe():
    """`--workers N` makes record_call genuinely concurrent, and the repo reports tokens
    and cost as MEASURED figures — a lost update silently under-reports spend."""
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from depguard.llm_meter import LLMMeter

    meter = LLMMeter()
    resp = SimpleNamespace(usage_metadata={"input_tokens": 10, "output_tokens": 5})
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: meter.record_call(resp), range(2000)))
    assert meter.calls == 2000
    assert meter.prompt_tokens == 20000
    assert meter.completion_tokens == 10000


def test_abstaining_and_guessing_face_the_same_denominator():
    """An unscoreable record must be EXCLUDED for both arms, not excluded for the guesser
    and a penalty for the abstainer. The abstain short-circuit used to run before the
    exclusion check, so `deterministic_script` — which always abstains, and is the control
    the whole comparison is anchored on — was the arm the asymmetry ran against."""
    eco, aid, name = LODASH
    rec = _record(eco, aid)
    # no published version is scoreable => neither arm can be graded here
    guesser = verify_range_reconstruction(
        {"events": [{"introduced": "0"}, {"fixed": "1.0.0"}], "versions": [], "abstain": False},
        ecosystem=eco, name=name, true_record=rec, published_versions=[],
    )
    abstainer = verify_range_reconstruction(
        None, ecosystem=eco, name=name, true_record=rec, published_versions=[],
    )
    assert guesser.status == "excluded"
    assert abstainer.status == "excluded", (
        "the abstaining arm was graded on a record the guessing arm was excluded from"
    )
    assert guesser.passed is None and abstainer.passed is None


def test_a_gold_abstain_record_is_still_scoreable_with_no_published_versions():
    """Guard against over-reaching: abstention correctness does not depend on the
    published list, so a gold-abstain seed must still be gradeable."""
    eco, rec = next(
        (p.parent.name, json.loads(p.read_text()))
        for p in sorted((CORPUS / "osv").rglob("*.json"))
        if gold_abstains(json.loads(p.read_text()))
    )
    name = rec["affected"][0]["package"]["name"]
    r = verify_range_reconstruction(None, ecosystem=eco, name=name,
                                    true_record=rec, published_versions=[])
    assert r.status == "abstained" and r.passed is True


def test_single_agent_also_refuses_to_dismiss_an_unresolvable_alert(monkeypatch):
    """The fail-unsafe fix must cover BOTH arms. graph.py's Pipeline._exec_check was fixed,
    but arms/single_agent.py carried the identical
        data = result["data"] if result["ok"] else {}
        pa["contained"] = bool(data.get("contained"))
    so on an error envelope the ReAct arm still turned "I could not resolve this range"
    into a shipped `affected: false` verdict — and fed that fabricated False back to its own
    policy through _summary. single_agent is one of the three ablation arms, so leaving it
    would mean the release notes claimed a bug class was removed while it still shipped."""
    from depguard.arms import single_agent as sa
    from depguard.arms.single_agent import canonical_policy, run_single_agent
    from depguard.envelope import err
    from golden.seeds import SEED_INPUTS

    monkeypatch.setattr(
        sa, "check_version_affected",
        lambda *a, **k: err("RANGE_UNRESOLVABLE", "every matching entry is undecidable"),
    )
    traj = run_single_agent(SEED_INPUTS["tp_lodash"], SNAP, policy=canonical_policy)

    dismissals = [v for v in traj["verdicts"] if v["affected"] is False]
    assert not dismissals, (
        "single_agent reported an unresolvable range as 'not affected': "
        f"{[v['alert_id'] for v in dismissals]}"
    )
    assert traj["final_answer"]["verdicts_summary"]["n_false_positive"] == 0
    assert traj["final_answer"]["verdicts_summary"]["n_unresolved"] == 1


def test_undecidable_alert_produces_no_source_agreement_evidence(monkeypatch):
    """The verdict was already suppressed, but `_exec_crosscheck` still ran and passed
    `pa.get("contained", False)` into crosscheck_second_source — writing an `agreement`
    derived from an answer the arm never had into a deps.dev Evidence row on the
    trajectory. Suppressing the verdict while shipping the evidence is half a fix."""
    from depguard import graph as graph_mod
    from depguard.envelope import err
    from depguard.graph import run_graph
    from golden.seeds import SEED_INPUTS

    monkeypatch.setattr(graph_mod, "check_version_affected",
                        lambda *a, **k: err("RANGE_UNRESOLVABLE", "undecidable"))
    traj = run_graph(SEED_INPUTS["tp_lodash"], SNAP, system_variant="deterministic_script")

    assert "crosscheck_second_source" not in [c["tool_name"] for c in traj["tool_calls"]]
    assert not [e for e in traj["evidence"] if e.get("source") == "deps.dev"
                and e.get("observed_agreement")]
