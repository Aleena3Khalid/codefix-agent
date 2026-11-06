"""Tests for codefix.llm using a fake Anthropic client (no network, no API key)."""

from types import SimpleNamespace

import pytest

from codefix.llm import LLM, LLMError, Usage

TOOL = {"name": "submit_diagnosis", "description": "x", "input_schema": {"type": "object", "properties": {}}}


class FakeClient:
    """Mimics the shape of anthropic.Anthropic(): client.messages.create(...)."""

    def __init__(self, content):
        self.sent = None
        self.messages = SimpleNamespace(create=self._create)
        self._content = content

    def _create(self, **kwargs):
        self.sent = kwargs
        return SimpleNamespace(
            content=self._content,
            usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
            stop_reason="tool_use",
        )


def test_call_tool_returns_tool_input_and_usage():
    block = SimpleNamespace(type="tool_use", name="submit_diagnosis", input={"summary": "ok"})
    client = FakeClient([block])
    answer, usage = LLM(model="claude-sonnet-5-5", client=client).call_tool("sys", "hello", TOOL)

    assert answer == {"summary": "ok"}
    assert (usage.input_tokens, usage.output_tokens) == (1200, 300)
    assert client.sent["tool_choice"] == {"type": "auto"}
    assert client.sent["tools"] == [TOOL]
    assert client.sent["messages"] == [{"role": "user", "content": "hello"}]


def test_missing_tool_call_raises():
    client = FakeClient([SimpleNamespace(type="text", text="I refuse")])
    with pytest.raises(LLMError):
        LLM(client=client).call_tool("sys", "hello", TOOL)


def test_cost_uses_price_table():
    usage = Usage(model="claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=1_000_000, latency_s=1)
    assert usage.cost_usd == pytest.approx(12.0)


def test_unknown_model_has_no_cost():
    assert Usage(model="mystery", input_tokens=10, output_tokens=10, latency_s=1).cost_usd is None