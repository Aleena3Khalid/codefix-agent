"""A small wrapper around the Anthropic API.

Every LLM call in the project goes through `LLM.call_tool`, so that:
- the model name lives in one place,
- tokens, cost and latency are measured for every call (needed on Day 4),
- tests can swap in a fake LLM and never spend money.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass

DEFAULT_MODEL = "claude-sonnet-5-5"

PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
}


@dataclass
class Usage:
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float

    @property
    def cost_usd(self) -> float | None:
        """Cost of this call, or None if the model has no price in PRICES."""
        if self.model not in PRICES:
            return None
        price_in, price_out = PRICES[self.model]
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000

    def to_dict(self) -> dict:
        data = asdict(self)
        data["cost_usd"] = self.cost_usd
        return data


class LLMError(RuntimeError):
    """Raised when the model does not return what we asked for."""


class LLM:
    def __init__(self, model: str | None = None, max_tokens: int = 2000, client=None):
        self.model = model or os.getenv("CODEFIX_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        self._client = client  # created on first use, so importing this file never needs an API key

    @property
    def client(self):
        if self._client is None:
            import anthropic  # imported here so tests without the package still run

            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        return self._client

    def call_tool(self, system: str, user: str, tool: dict) -> tuple[dict, Usage]:
        """Send one message and ask the model to answer by calling `tool`.

        Some models reject a forced tool_choice, so we use "auto" and rely on the
        system prompt telling the model to answer only through the tool. If it
        replies with plain text instead, LLMError is raised below.

        Returns the tool's input (a dict matching the tool's JSON schema) and usage stats.
        """
        start = time.perf_counter()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "auto"},
        )
        usage = Usage(
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_s=round(time.perf_counter() - start, 3),
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == tool["name"]:
                return dict(block.input), usage
        raise LLMError(f"Model did not call {tool['name']!r} (stop_reason={response.stop_reason})")