from __future__ import annotations

import json

import httpx
import pytest

from ov.agent.engine.cancel import Cancel
from ov.agent.integrations import chat_completions, copilot
from ov.agent.integrations.chat_completions import Endpoint, ignore

COPILOT_USAGE = {"token_details": [{"token_type": "output", "token_count": 4}], "total_nano_aiu": 4_900_000_000}


class StreamError(Exception):
    pass


def _endpoint() -> Endpoint:
    return Endpoint(name="Test", url="https://api", headers={}, error=StreamError, usage_of=copilot.usage_of)


def _body(chunks: list[dict]) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def test_a_stream_keeps_text_reasoning_tool_calls_and_usage():
    chunks = [
        {"choices": [{"index": 0, "delta": {"reasoning_content": "Think "}}]},
        {"choices": [{"index": 0, "delta": {"reasoning": "more."}}]},
        {"choices": [{"index": 0, "delta": {"content": "ok"}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"name": "ov_sql"}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]}}]},
        {"choices": [], "copilot_usage": COPILOT_USAGE},
    ]
    thoughts: list[str] = []

    result = chat_completions._read_stream(
        _endpoint(), httpx.Response(200, content=_body(chunks)), ignore, thoughts.append
    )

    assert (result.text, result.reasoning, thoughts) == ("ok", "Think more.", ["Think ", "more."])
    assert [c["function"] for c in result.tool_calls] == [{"name": "ov_sql", "arguments": "{}"}]
    assert result.usage is not None and result.usage.nano == 4_900_000_000


def test_chat_retries_a_dropped_connection_before_any_text(monkeypatch):
    calls = []

    def flaky(endpoint, payload, cancel, on_text, on_reasoning):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadError("connection reset")
        on_text("hi")
        return "ok"

    monkeypatch.setattr(chat_completions, "_stream_once", flaky)
    monkeypatch.setattr(chat_completions, "RETRY_BASE_SECONDS", 0)

    assert chat_completions.stream(_endpoint(), {}, cancel=Cancel(), on_text=ignore) == "ok"
    assert len(calls) == 2


def test_chat_does_not_retry_after_reasoning_streamed(monkeypatch):
    def dropped(endpoint, payload, cancel, on_text, on_reasoning):
        on_reasoning("partial")
        raise httpx.ReadError("connection reset")

    monkeypatch.setattr(chat_completions, "_stream_once", dropped)

    with pytest.raises(StreamError, match="Lost the connection to Test"):
        chat_completions.stream(_endpoint(), {}, cancel=Cancel(), on_text=ignore)
