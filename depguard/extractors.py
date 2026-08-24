"""Range extractors for the prose slice (§5.1, v1.2.0).

Each takes the surviving advisory prose and returns a proposal
`{events, versions, abstain}` that `verifier.verify_range_reconstruction` (P5) scores.
Three implementations, one per arm:

  null_extractor   the `deterministic_script` arm. There is no prose parser in the
                   deterministic pipeline, and that is the point: with `ranges` and
                   `versions` redacted, `oracle.record_containment` RAISES
                   RangeUnresolvableError (asserted in tests/test_prose_slice.py).
                   The arm abstains because it structurally cannot answer.

  regex_extractor  the strongest honest NON-LLM baseline. It exists to pre-empt the
                   obvious rebuttal — "you should have just written the parser" — with
                   a measured number instead of an opinion. It is a good-faith effort,
                   not a straw man: it handles the branch form ("2.2 before 2.2.28"),
                   the open form ("before X", "prior to X"), inclusive forms ("through
                   X", "X and earlier"), and explicit comparators.

  llm_extractor    lives in depguard/llm_extractor.py, NOT here. This module is kept
                   provably network-free (tests/test_external_tools.py greps the tool
                   and data layer for network references and this file is not on the
                   allowlist), because the regex baseline is a scientific control: it
                   must be impossible for it to have consulted anything but the frozen
                   bytes it was handed.

An extractor MUST abstain when it finds nothing, and must never invent a range: P5
scores abstention as correct exactly when the prose carries no version token, so both
always-abstain and always-guess strategies are punished.
"""

from __future__ import annotations

import re

from depguard.redact import has_version_token

__all__ = ["null_extractor", "regex_extractor", "ABSTAIN"]

ABSTAIN = {"events": [], "versions": [], "abstain": True}

_V = r"\d+(?:\.\d+)+(?:[._-]?(?:a|b|c|rc|alpha|beta|dev|post)\.?\d*)?"

# Ordered by specificity: the first pattern that matches a span wins, so the two-sided
# branch form is tried before the one-sided "before X".
_BRANCH = re.compile(rf"(?<![\w.])({_V})\s+(?:before|prior to|through)\s+({_V})", re.I)
_BETWEEN = re.compile(rf"between\s+({_V})\s+and\s+({_V})", re.I)
_RANGE_OP = re.compile(rf">=?\s*({_V})\s*(?:,|\s|and)+\s*<\s*({_V})", re.I)
_BEFORE = re.compile(rf"(?:before|prior to|earlier than|older than|up to but not including)\s+({_V})", re.I)
_FIXED_IN = re.compile(rf"(?:fixed|patched|resolved|corrected)\s+in\s+(?:version\s+)?({_V})", re.I)
_THROUGH = re.compile(rf"(?:through|up to and including|<=)\s*({_V})", re.I)
_AND_EARLIER = re.compile(rf"({_V})\s+(?:and\s+)?(?:earlier|below|and\s+prior|or\s+earlier)", re.I)


def null_extractor(prose: str, published: list[str], ecosystem: str) -> dict:
    """The deterministic arm has no prose parser — by construction, not by omission."""
    return dict(ABSTAIN)


def regex_extractor(prose: str, published: list[str], ecosystem: str) -> dict:
    """Best-effort grammar over the advisory prose. Honest baseline, not a straw man."""
    text = " ".join((prose or "").split())
    if not has_version_token(text):
        return dict(ABSTAIN)

    events: list[dict] = []
    consumed: list[tuple[int, int]] = []

    def free(match) -> bool:
        s, e = match.span()
        return not any(s < ce and cs < e for cs, ce in consumed)

    def take(match) -> None:
        consumed.append(match.span())

    # 1. two-sided branch forms first — "2.2 before 2.2.28, 3.2 before 3.2.13"
    for pattern, inclusive in ((_BRANCH, False), (_BETWEEN, True), (_RANGE_OP, False)):
        for m in pattern.finditer(text):
            if not free(m):
                continue
            take(m)
            lo, hi = m.group(1), m.group(2)
            events.append({"introduced": lo})
            events.append({"last_affected": hi} if inclusive else {"fixed": hi})

    # 2. one-sided forms, only over spans not already claimed
    for pattern in (_BEFORE, _FIXED_IN):
        for m in pattern.finditer(text):
            if not free(m):
                continue
            take(m)
            events.append({"introduced": "0"})
            events.append({"fixed": m.group(1)})
    for pattern in (_THROUGH, _AND_EARLIER):
        for m in pattern.finditer(text):
            if not free(m):
                continue
            take(m)
            events.append({"introduced": "0"})
            events.append({"last_affected": m.group(1)})

    if not events:
        return dict(ABSTAIN)
    return {"events": events, "versions": [], "abstain": False}
