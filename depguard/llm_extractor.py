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
"""

from __future__ import annotations

from depguard.extractors import ABSTAIN

__all__ = ["llm_extractor"]


_LLM_PROMPT = """You are reading a security advisory. The machine-readable affected-version \
ranges have been removed; only the prose remains. Recover the affected range.

PACKAGE: {ecosystem}/{name}

ADVISORY TEXT:
{prose}

PUBLISHED VERSIONS (the complete released history of this package, oldest first):
{published}

Reply with ONE JSON object and nothing else:
  {{"events": [...], "abstain": false}}

`events` uses the OSV interval convention, in order:
  {{"introduced": "X"}}  opens a range at X, INCLUSIVE. Use "0" for "from the beginning".
  {{"fixed": "Y"}}       closes the open range at Y, EXCLUSIVE (Y itself is NOT affected).
  {{"last_affected": "Z"}} closes the open range at Z, INCLUSIVE (Z IS affected).

Rules:
- Emit one introduced/close PAIR per affected branch. "2.2 before 2.2.28, 3.2 before
  3.2.13" is two pairs: introduced 2.2 / fixed 2.2.28, then introduced 3.2 / fixed 3.2.13.
- "before X" / "prior to X" with no lower bound is introduced "0" then fixed X.
- "through X" / "X and earlier" is introduced "0" then last_affected X.
- Use version strings exactly as they appear in the published list where possible.
- If the text names NO versions at all and you would be guessing, reply
  {{"events": [], "abstain": true}}. Abstaining is scored CORRECT when the advisory
  genuinely carries no version information, and WRONG otherwise — so do not abstain
  merely because the text is awkward.
"""


def llm_extractor(prose: str, published: list[str], ecosystem: str, *, name: str = "") -> dict:
    """Reconstruct the affected range with the LLM under test.

    Unlike the v0.1 `multi_agent` planner prompt — which enumerated the canonical plan
    verbatim and so left the model no degrees of freedom over anything scored — this
    prompt CANNOT contain the answer: the range was redacted out of the record before
    the prose ever reached it. What the model produces is what gets scored."""
    import json
    import os
    import re as _re

    from langchain_openai import ChatOpenAI

    from depguard.llm_meter import METER

    client = ChatOpenAI(
        model=os.environ.get("LLM_MODEL", "deepseek-v4-flash"),
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        api_key=os.environ["LLM_API_KEY"],
        temperature=0,
    )
    shown = published if len(published) <= 200 else published[:100] + ["..."] + published[-100:]
    prompt = _LLM_PROMPT.format(
        ecosystem=ecosystem, name=name, prose=(prose or "")[:6000],
        published=", ".join(shown),
    )
    for _ in range(2):
        resp = client.invoke(prompt)
        METER.record_call(resp)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        match = _re.search(r"\{.*\}", text, _re.S)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        events = parsed.get("events")
        if not isinstance(events, list):
            continue
        clean = [e for e in events if isinstance(e, dict) and len(e) == 1
                 and next(iter(e)) in ("introduced", "fixed", "last_affected")]
        return {"events": clean, "versions": [], "abstain": bool(parsed.get("abstain"))}
    # Two unparseable replies. Abstaining is the honest failure mode — it is scored WRONG
    # on every decidable record, so a broken extractor cannot hide behind it.
    METER.record_fallback()
    return dict(ABSTAIN)
