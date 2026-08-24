"""The four mechanical trajectory metrics (DECISIONS.md §4.1) + correctness.

UNDECIDABLE ALERTS ARE TREATED DIFFERENTLY BY DIFFERENT METRICS, on purpose:
`correctness` EXCLUDES them (the oracle cannot decide the alert, so it is not the arm's
fault); `groundedness` still divides by the full alert set, so an unanswered alert counts
as ungrounded (the arm gathered no evidence entailing a verdict, which IS about the arm);
and `plan_adherence` scores executed steps only, so a step marked `failed` earns no credit.
Three questions, three answers — "could the oracle decide this?", "did the arm support what
it said?", "did the arm follow the plan?" — and they are not required to agree.

Each metric returns `(score ∈ [0,1], fails: list[str])` per trajectory. Nothing here
is an LLM judgment — every number is recomputed from the trajectory + its gold
sidecar (and, for groundedness, the cited Evidence rows only). Aggregate across the
golden set by averaging per-trajectory scores (paired-bootstrap CIs live in the D8
ablation, out of scope here).
"""

from __future__ import annotations

import json
from pathlib import Path

from depguard.oracle import RangeUnresolvableError, record_containment
from depguard.tools.pure import minimal_fix_gold

_SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"


def _tool_key_args() -> dict:
    return json.loads((_SCHEMAS / "tool_key_args.json").read_text())


def _extract_scored_args(tool_name: str, arguments: dict, registry: dict) -> dict:
    """Pull the scored-arg subset from a tool_call's arguments, traversing dotted
    keys (e.g. `osv_record.id` → arguments['osv_record']['id']). §2.5."""
    out = {}
    for key in registry.get(tool_name, []):
        if "." in key:
            parent, child = key.split(".", 1)
            node = arguments.get(parent)
            out[key] = node.get(child) if isinstance(node, dict) else None
        else:
            out[key] = arguments.get(key)
    return out


def _callset(calls):
    """Multiset of (tool_name, frozenset(scored_args)) — order-insensitive."""
    from collections import Counter
    return Counter((c[0], frozenset(c[1].items())) for c in calls)


# --------------------------------------------------------------------------- #
# 1. TOOL-SELECTION ACCURACY (§4.1.1)
# --------------------------------------------------------------------------- #

def tool_selection(trajectory: dict, gold: dict) -> dict:
    """Order-insensitive (tool_name, scored-args) set-match vs gold; spurious calls
    hurt precision, missing calls hurt recall. Reports precision/recall/F1."""
    reg = _tool_key_args()
    pred = _callset(
        (tc["tool_name"], _extract_scored_args(tc["tool_name"], tc["arguments"], reg))
        for tc in trajectory["tool_calls"]
    )
    goldset = _callset((g["tool_name"], g["scored_args"]) for g in gold["gold_tool_calls"])

    matched = sum((pred & goldset).values())
    n_pred = sum(pred.values())
    n_gold = sum(goldset.values())
    precision = matched / n_pred if n_pred else 1.0
    recall = matched / n_gold if n_gold else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    fails = []
    for call, n in (goldset - pred).items():
        fails.append(f"missing gold call x{n}: {call[0]} {dict(call[1])}")
    for call, n in (pred - goldset).items():
        fails.append(f"spurious call x{n}: {call[0]} {dict(call[1])}")
    return {"score": f1, "precision": precision, "recall": recall, "f1": f1, "fails": fails}


# --------------------------------------------------------------------------- #
# 2. ACTION-ADVANCEMENT (§4.1.2)
# --------------------------------------------------------------------------- #

def verdict_yield(trajectory: dict) -> dict:
    """|distinct alerts given a verdict| / |alerts given| (§4.1.2, v1.1.0).

    Replaces `action_advancement`, which was |steps advancing a new alert| / |executed
    steps|. On a one-alert-per-trajectory corpus that numerator is always 0 or 1, so the
    old metric reduced to `1 / n_executed_steps` and scored an arm HIGHER for doing less
    work. On the shipped v0.1 `single_agent` rows it was ANTI-correlated with correctness
    (r = -0.172): its nine 4-step runs took the experiment's best value, 0.2500, while
    being 3-of-9 correct, and its six full 7-step runs took the worst value, 0.1429, while
    being 6-of-6 correct — which is how results/ablation_v01.md came to mark the
    deterministic arm "significantly worse" than an arm that got 13 of 29 alerts wrong.

    `verdict_yield` is a coverage metric, not an efficiency one: it is invariant to step
    count and makes abandonment (the `tp_axios` shape) visible as a loss."""
    alert_ids = {a["alert_id"] for a in trajectory["input"]["alerts"]}
    answered = {v["alert_id"] for v in trajectory["verdicts"]} & alert_ids
    fails = [f"{aid}: no verdict emitted" for aid in sorted(alert_ids - answered)]
    score = len(answered) / len(alert_ids) if alert_ids else 1.0
    return {"score": score, "answered": len(answered), "alerts": len(alert_ids),
            "fails": fails}


# --------------------------------------------------------------------------- #
# 3. PLAN-ADHERENCE (alert-grouped, §4.1.3 / v1.1.0)
# --------------------------------------------------------------------------- #

def _normalized_levenshtein(a: list, b: list) -> float:
    if not a and not b:
        return 0.0
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n] / max(m, n)


def _group_actions(steps, executed_only):
    """alert_id -> [actions]; None-alert steps collapse to the single control group."""
    groups: dict = {}
    for s in steps:
        if executed_only and s.get("status") != "executed":
            continue
        key = s["alert_id"] if s["alert_id"] is not None else "__control__"
        groups.setdefault(key, []).append(s["action"])
    return groups


def plan_adherence(trajectory: dict, gold: dict) -> dict:
    """Partition executed steps by alert_id; per group 1 − normLevenshtein(exec, gold);
    all null-alert steps form ONE control group. Denominator = n_alerts + 1 when a
    control step exists, else n_alerts (§4.1.3, pinned). Reordering independent alerts
    incurs no penalty; a within-alert swap does."""
    exec_groups = _group_actions(trajectory["plan"], executed_only=True)
    gold_groups = _group_actions(gold["gold_plan"], executed_only=False)

    alert_keys = [k for k in gold_groups if k != "__control__"]
    has_control = "__control__" in gold_groups
    denom = len(alert_keys) + (1 if has_control else 0)
    if denom == 0:
        return {"score": 1.0, "fails": []}

    total = 0.0
    fails = []
    keys = alert_keys + (["__control__"] if has_control else [])
    for k in keys:
        g = gold_groups.get(k, [])
        e = exec_groups.get(k, [])
        s = 1.0 - _normalized_levenshtein(e, g)
        total += s
        if s < 1.0:
            fails.append(f"group {k}: adherence {s:.2f} (exec={e} gold={g})")
    return {"score": total / denom, "fails": fails}


# --------------------------------------------------------------------------- #
# 4. GROUNDEDNESS (§4.1.4) + CORRECTNESS
# --------------------------------------------------------------------------- #

def _reconstruct_record(osv_ev: dict) -> dict:
    ranges = []
    if osv_ev.get("range_events"):
        ranges = [{"type": osv_ev["range_type"], "events": osv_ev["range_events"]}]
    return {
        "id": osv_ev["advisory_id"],
        "withdrawn": osv_ev.get("withdrawn"),
        "aliases": [],
        "affected": [{
            "package": osv_ev["affected_package"],
            "ranges": ranges,
            "versions": osv_ev.get("enumerated_versions") or [],
        }],
    }


def groundedness(trajectory: dict) -> dict:
    """Fraction of alerts (one verdict expected per alert, §3.3) whose emitted verdict's
    `affected` AND `minimal_fixed_version` are entailed by their CITED Evidence rows under
    the verifier rule — recomputed from evidence only. Denominator is the ALERT set: an
    alert with NO emitted verdict is ungrounded (never dropped), so an arm cannot inflate
    this metric by skipping alerts. A hallucinated verdict not supported by its evidence
    scores < 1 (§4.1.4)."""
    ev_by_id = {e["evidence_id"]: e for e in trajectory["evidence"]}
    alerts = trajectory["input"]["alerts"]
    alert_eco = {a["alert_id"]: a["ecosystem"] for a in alerts}
    alert_ver = {a["alert_id"]: a["pinned_version"] for a in alerts}
    v_by_alert = {v["alert_id"]: v for v in trajectory["verdicts"]}
    grounded = 0
    fails = []
    for a in alerts:
        aid = a["alert_id"]
        v = v_by_alert.get(aid)
        if v is None:
            fails.append(f"{aid}: no verdict emitted (expected one)")
            continue
        osv_ev = next((ev_by_id[i] for i in v["evidence_ids"]
                       if ev_by_id.get(i, {}).get("source") == "osv"), None)
        dd_ev = next((ev_by_id[i] for i in v["evidence_ids"]
                      if ev_by_id.get(i, {}).get("source") == "deps.dev"), None)
        if osv_ev is None:
            fails.append(f"{aid}: no cited OSV evidence")
            continue
        record = _reconstruct_record(osv_ev)
        eco = alert_eco[aid]
        name = osv_ev["affected_package"]["name"]
        ver = alert_ver[aid]
        try:
            contained = record_containment(record, eco, name, ver).contained
        except (RangeUnresolvableError, Exception):  # noqa: BLE001
            fails.append(f"{aid}: evidence does not decide containment")
            continue
        withdrawn = osv_ev.get("withdrawn") is not None
        affected_ok = v["affected"] == (contained and not withdrawn)
        minfix_ok = True
        if v["minimal_fixed_version"] is not None or (contained and not withdrawn):
            published = dd_ev.get("published_versions", []) if dd_ev else []
            gold_fix = None
            if not withdrawn:
                gold_fix, _r, _c = minimal_fix_gold(eco, name, ver, record, published)
            minfix_ok = v["minimal_fixed_version"] == gold_fix
        if affected_ok and minfix_ok:
            grounded += 1
        else:
            fails.append(f"{aid}: verdict not entailed by evidence "
                         f"(affected_ok={affected_ok}, minfix_ok={minfix_ok})")
    score = grounded / len(alerts) if alerts else 1.0
    return {"score": score, "fails": fails}


_PROBE_VERDICT = {
    "alert_id": None, "affected": False, "minimal_fixed_version": None,
    "withdrawn": False, "cvss3_score": None, "evidence_ids": [],
    "source_agreement": "single_source", "reconciliation_note": "",
}


def _verify_alert(verify_verdict, alert: dict, verdict: dict | None, snapshot):
    """Score one alert with the §5 verifier, sourcing the frozen evidence the verifier
    needs (OSV record, published versions, deps.dev observation) from the snapshot.

    `verdict=None` (the arm emitted nothing) is still passed through the verifier with a
    neutral probe, because EXCLUSION is a property of the gold side alone — it must be
    decided identically whether or not the arm answered. `verify_verdict` checks
    exclusion before reading any verdict field, so the probe never reaches a predicate:
    `correctness` returns on `verdict is None` as soon as the alert is known scoreable.
    """
    from depguard.agreement import observe_from_extract
    from depguard.graph import _find_record
    from depguard.tools.external import osv_query_package, resolve_published_versions
    from depguard.verifier import VerdictScore

    eco, name, version = alert["ecosystem"], alert["name"], alert["pinned_version"]
    q = osv_query_package(eco, name, version, snapshot=snapshot)
    record = _find_record(q["data"]["advisories"] if q["ok"] else [], alert["advisory_id"])
    if record is None:
        return VerdictScore(status="excluded", exclusion_reason="advisory_not_in_snapshot",
                            predicates={}, correct=None, agreement_metric_eligible=False)
    pub = resolve_published_versions(eco, name, snapshot=snapshot)
    published = pub["data"]["versions"] if pub["ok"] else []
    return verify_verdict(
        verdict if verdict is not None else dict(_PROBE_VERDICT, alert_id=alert["alert_id"]),
        ecosystem=eco,
        name=name,
        pinned_version=version,
        osv_record=record,
        published_versions=published,
        depsdev=observe_from_extract(snapshot.read_extract(eco, name), version),
    )

def correctness(trajectory: dict, gold: dict, snapshot) -> dict:
    """Fraction of SCOREABLE gold verdicts (one per alert, §3.3) that pass all four
    §5 predicates, as judged by `depguard.verifier.verify_verdict` — the same scorer
    DECISIONS.md §5 defines. Before v1.1.0 this was a private field-equality lookalike
    that never called the verifier, so neither the P4 non-empty-`reconciliation_note`
    rule nor the exclusion path was ever enforced on a published number.

    Denominator is the GOLD set, so an alert with NO emitted verdict counts as wrong —
    never silently excluded (that would let an arm inflate this metric by skipping hard
    alerts). The one exception is an alert the oracle itself cannot score (empty E_A
    after the membership filter, or unresolvable ranges): `verify_verdict` returns
    `status="excluded"` and the alert leaves the denominator entirely, because "not
    decidable from the frozen evidence" is not a failure of the arm. Separate from
    groundedness (§4.1.4)."""
    from depguard.verifier import verify_verdict

    gold_verdicts = gold["gold_verdicts"]
    v_by_alert = {v["alert_id"]: v for v in trajectory["verdicts"]}
    alerts = {a["alert_id"]: a for a in trajectory["input"]["alerts"]}
    correct = 0
    scored = 0
    fails = []
    for g in gold_verdicts:
        aid = g["alert_id"]
        alert = alerts.get(aid)
        if alert is None:  # gold references an alert not in the input — malformed pair
            fails.append(f"{aid}: gold verdict has no matching alert in the input")
            scored += 1
            continue
        v = v_by_alert.get(aid)
        result = _verify_alert(verify_verdict, alert, v, snapshot)
        if result.status == "excluded":
            fails.append(f"{aid}: excluded ({result.exclusion_reason}) — not scoreable")
            continue
        scored += 1
        if v is None:
            fails.append(f"{aid}: no verdict emitted (expected one)")
            continue
        if result.correct:
            correct += 1
        else:
            missed = {n: (p.actual, p.gold) for n, p in result.predicates.items()
                      if p.passed is False}
            fails.append(f"{aid}: {missed}")
    score = correct / scored if scored else 1.0
    return {"score": score, "fails": fails}


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #

METRICS = ("tool_selection", "verdict_yield", "plan_adherence",
           "groundedness", "correctness")


def score_trajectory(trajectory: dict, gold: dict, snapshot) -> dict:
    """`snapshot` is required (v1.1.0): `correctness` now routes through the §5
    verifier, which needs the frozen OSV record, published-version list and deps.dev
    observation for each alert. Both call sites already hold a Snapshot."""
    return {
        "tool_selection": tool_selection(trajectory, gold),
        "verdict_yield": verdict_yield(trajectory),
        "plan_adherence": plan_adherence(trajectory, gold),
        "groundedness": groundedness(trajectory),
        "correctness": correctness(trajectory, gold, snapshot),
    }


def aggregate(per_trajectory: list[dict]) -> dict:
    """Mean of each metric's `score` across trajectories."""
    out = {}
    for m in METRICS:
        scores = [t[m]["score"] for t in per_trajectory]
        out[m] = sum(scores) / len(scores) if scores else 1.0
    return out
