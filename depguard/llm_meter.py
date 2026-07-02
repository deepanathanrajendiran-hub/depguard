"""A process-global meter for LLM usage during one arm run (D9 review fix).

The ablation resets it before each arm and reads it after, so the report can carry measured
tokens / cost / call-count per arm AND — critically — the **planner fallback count**. A
silent fallback (the multi_agent LLM planner failing twice and quietly running the
deterministic plan, graph.py) would make the two arms produce identical numbers for the
WRONG reason; counting it means a fallback > 0 gets a footnote, never silence.

Global mutable state is acceptable here: arm runs are strictly sequential in the ablation
harness, and scripted (keyless) test policies never touch the LLM, so the meter stays at 0.

Pricing is DeepSeek's published rate; it is an external constant (not a measurement) and is
stated in the report so a reader can re-derive cost from the measured token counts.
"""

from __future__ import annotations

# DeepSeek published pricing, USD per 1M tokens (verify/adjust in one place if it changes).
PRICE_PER_MTOK = {"input": 0.27, "output": 1.10}


class LLMMeter:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.fallbacks = 0

    def record_call(self, response) -> None:
        """Count one LLM call and accumulate its token usage from a langchain AIMessage."""
        self.calls += 1
        prompt, completion = _usage(response)
        self.prompt_tokens += prompt
        self.completion_tokens += completion

    def record_fallback(self) -> None:
        self.fallbacks += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def cost_usd(self) -> float:
        return (self.prompt_tokens * PRICE_PER_MTOK["input"]
                + self.completion_tokens * PRICE_PER_MTOK["output"]) / 1_000_000

    def snapshot(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd(),
            "fallbacks": self.fallbacks,
        }


def _usage(response) -> tuple[int, int]:
    """(prompt_tokens, completion_tokens) from a langchain response, tolerant of shape."""
    um = getattr(response, "usage_metadata", None)
    if um:
        return int(um.get("input_tokens", 0) or 0), int(um.get("output_tokens", 0) or 0)
    md = getattr(response, "response_metadata", {}) or {}
    tu = md.get("token_usage") or md.get("usage") or {}
    return int(tu.get("prompt_tokens", 0) or 0), int(tu.get("completion_tokens", 0) or 0)


METER = LLMMeter()
