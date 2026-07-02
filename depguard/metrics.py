"""The four mechanical trajectory metrics (DECISIONS.md §4.1) + correctness.

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
_MINFIX_ECOSYSTEMS = frozenset({"npm", "crates.io", "Go"})


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

def action_advancement(trajectory: dict) -> dict:
    """|executed steps that advanced a previously-unverdicted alert| / |executed
    steps|. A redundant repeat (an already-verdicted alert) does not count."""
    executed = [s for s in trajectory["plan"] if s["status"] == "executed"]
    verdicted: set = set()
    advancing = 0
    fails = []
    for s in executed:
        pvf = s.get("produced_verdict_for")
        if pvf is not None and pvf not in verdicted:
            advancing += 1
            verdicted.add(pvf)
        elif pvf is not None:
            fails.append(f"redundant advance for already-verdicted {pvf}")
    score = advancing / len(executed) if executed else 0.0
    return {"score": score, "advancing": advancing, "executed": len(executed), "fails": fails}


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


def correctness(trajectory: dict, gold: dict) -> dict:
    """Fraction of GOLD verdicts (one per alert, §3.3) exactly matching the emitted verdict
    on the verifier-scored fields (affected, withdrawn, source_agreement always;
    minimal_fixed_version only on minimal-fix ecosystems, §5 P2). Denominator is the gold
    set, so an alert with NO emitted verdict counts as wrong — never silently excluded
    (that would let an arm inflate this metric by skipping hard alerts). Separate from
    groundedness (§4.1.4)."""
    gold_verdicts = gold["gold_verdicts"]
    v_by_alert = {v["alert_id"]: v for v in trajectory["verdicts"]}
    alert_eco = {a["alert_id"]: a["ecosystem"] for a in trajectory["input"]["alerts"]}
    correct = 0
    fails = []
    for g in gold_verdicts:
        aid = g["alert_id"]
        v = v_by_alert.get(aid)
        if v is None:
            fails.append(f"{aid}: no verdict emitted (expected one)")
            continue
        fields = ["affected", "withdrawn", "source_agreement"]
        if alert_eco.get(aid) in _MINFIX_ECOSYSTEMS:
            fields.append("minimal_fixed_version")
        if all(v.get(f) == g.get(f) for f in fields):
            correct += 1
        else:
            diff = {f: (v.get(f), g.get(f)) for f in fields if v.get(f) != g.get(f)}
            fails.append(f"{aid}: {diff}")
    score = correct / len(gold_verdicts) if gold_verdicts else 1.0
    return {"score": score, "fails": fails}


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #

METRICS = ("tool_selection", "action_advancement", "plan_adherence",
           "groundedness", "correctness")


def score_trajectory(trajectory: dict, gold: dict) -> dict:
    return {
        "tool_selection": tool_selection(trajectory, gold),
        "action_advancement": action_advancement(trajectory),
        "plan_adherence": plan_adherence(trajectory, gold),
        "groundedness": groundedness(trajectory),
        "correctness": correctness(trajectory, gold),
    }


def aggregate(per_trajectory: list[dict]) -> dict:
    """Mean of each metric's `score` across trajectories."""
    out = {}
    for m in METRICS:
        scores = [t[m]["score"] for t in per_trajectory]
        out[m] = sum(scores) / len(scores) if scores else 1.0
    return out
