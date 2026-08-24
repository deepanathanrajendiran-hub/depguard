"""The LLM range extractor for the prose slice (§5.1, v1.2.0).

Separate module from `depguard/extractors.py` on purpose. That module holds the null and
regex extractors and is kept provably network-free — `tests/test_external_tools.py` greps
the tool and data layer for network references and only graph.py, otel.py,
single_agent.py and this file are exempt. The regex arm is a scientific control, so it
must be impossible for it to have consulted anything but the frozen bytes it was handed;
keeping the LLM client out of that module is what makes the guarantee mechanical rather
than a promise.

Note this extractor is deliberately NOT exposed through depguard/mcp_server.py. That
server documents "no network, no API key" and reads only the frozen corpus; publishing an
LLM-calling tool there would quietly break the invariant its users rely on.

TWO MEASURED DESIGN DECISIONS, both from live runs against deepseek-v4-flash:

1. **The prompt does NOT include the published-version list.** An earlier version pasted
   in up to 200 published versions as grounding. Measured on GHSA-24wv-mv5m-xv4h (redis,
   168 published versions): with the list, one call took 176 s and burned 24,368 reasoning
   tokens to produce 142 characters of output; without it, 72 s and 10,144 reasoning
   tokens for the same answer. Dropping it is also the fairer experiment — the regex
   baseline works from prose alone, and `materialize_proposal` clamps any claim to the
   published list afterwards regardless, so exact version-string matching buys nothing.

2. **Event shapes are normalised, not rejected.** The model naturally emits one object per
   interval — `{"introduced": "0", "fixed": "4.3.6"}` — rather than OSV's strict
   one-key-per-event form. The first parser required `len(event) == 1` and silently
   dropped those, turning a CORRECT reconstruction into an empty proposal scored as wrong.
   Scoring a model down for a formatting preference is exactly the kind of silent
   measurement bug this repo exists to catch, so both spellings are accepted and must
   reach the same P5 verdict (asserted in tests/test_prose_slice.py).
"""

from __future__ import annotations

import json
import os
import re

from depguard.extractors import ABSTAIN

__all__ = ["llm_extractor"]

_EVENT_KEYS = ("introduced", "fixed", "last_affected")

_LLM_PROMPT = """Recover the affected version range of this security advisory from its prose.

PACKAGE: {ecosystem}/{name}

ADVISORY TEXT:
{prose}

Reply with ONE JSON object and nothing else:
{{"events": [...], "abstain": false}}

`events` uses the OSV interval convention, in order:
  {{"introduced": "X"}}    opens a range at X, INCLUSIVE. Use "0" for "from the beginning".
  {{"fixed": "Y"}}         closes the open range at Y, EXCLUSIVE (Y itself is NOT affected).
  {{"last_affected": "Z"}} closes the open range at Z, INCLUSIVE (Z IS affected).

Rules:
- Emit one introduced/close PAIR per affected branch. "2.2 before 2.2.28, 3.2 before
  3.2.13" is two pairs: introduced 2.2 / fixed 2.2.28, then introduced 3.2 / fixed 3.2.13.
- "before X" / "prior to X" with no lower bound is introduced "0" then fixed X.
- "through X" / "X and earlier" is introduced "0" then last_affected X.
- If the text names NO versions at all and you would be guessing, reply
  {{"events": [], "abstain": true}}. Abstaining is scored CORRECT when the advisory
  genuinely carries no version information, and WRONG otherwise — so do not abstain
  merely because the text is awkward.

Answer directly. Do not deliberate at length.
"""


def _normalize_events(events) -> list[dict]:
    """Accept both the strict OSV one-key-per-event form and the paired form the model
    actually emits, and drop anything that is neither.

    Order matters: an interval's `introduced` must precede its close, because
    `redact.expand_events` consumes the list sequentially exactly as `oracle._intervals`
    does. Within a paired object the boundary keys are emitted in `_EVENT_KEYS` order,
    which puts `introduced` first."""
    out: list[dict] = []
    if not isinstance(events, list):
        return out
    for event in events:
        if not isinstance(event, dict):
            continue
        for key in _EVENT_KEYS:
            if key in event and isinstance(event[key], (str, int, float)):
                out.append({key: str(event[key])})
    return out


def llm_extractor(prose: str, published: list[str], ecosystem: str, *, name: str = "") -> dict:
    """Reconstruct the affected range with the LLM under test.

    Unlike the v0.1 `multi_agent` planner prompt — which enumerated the canonical plan
    verbatim and so left the model no degrees of freedom over anything scored — this
    prompt CANNOT contain the answer: the range was redacted out of the record before the
    prose ever reached it. What the model produces is what gets scored.

    `published` is accepted for signature parity with the other extractors and is
    deliberately unused; see the module docstring."""
    from langchain_openai import ChatOpenAI

    from depguard.llm_meter import METER

    client = ChatOpenAI(
        model=os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        api_key=os.environ["LLM_API_KEY"],
        temperature=0,
        timeout=180,
        max_retries=1,
    )
    prompt = _LLM_PROMPT.format(
        ecosystem=ecosystem, name=name, prose=(prose or "")[:6000],
    )
    for _ in range(2):
        try:
            resp = client.invoke(prompt)
        except Exception:
            continue  # a timeout or transport error gets one more attempt
        METER.record_call(resp)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        return {
            "events": _normalize_events(parsed.get("events")),
            "versions": [],
            "abstain": bool(parsed.get("abstain")),
        }
    # Two unparseable or failed replies. Abstaining is the honest failure mode — P5 scores
    # it WRONG on every decidable record, so a broken extractor cannot hide behind it.
    METER.record_fallback()
    return dict(ABSTAIN)
