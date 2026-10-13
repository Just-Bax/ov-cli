from __future__ import annotations

import json

import httpx
import pytest

from ov.agent.integrations.copilot import Usage, usage_of
from ov.agent.storage import db

COPILOT_USAGE = {
    "token_details": [
        {"token_type": "input", "token_count": 12000},
        {"token_type": "cache_read", "token_count": 3000},
        {"token_type": "output", "token_count": 40},
    ],
    "total_nano_aiu": 4_900_000_000,
}


def test_copilot_usage_is_read_from_a_reply():
    assert usage_of({"choices": []}) is None
    usage = usage_of({"copilot_usage": COPILOT_USAGE})
    assert usage == Usage(tokens={"input": 12000, "cache_read": 3000, "output": 40}, nano=4_900_000_000)


def test_the_streamed_usage_chunk_is_kept():
    from ov.agent.integrations.copilot import _read_stream

    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "ok"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "copilot_usage": COPILOT_USAGE},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    result = _read_stream(httpx.Response(200, content=body.encode()), lambda _: None)
    assert result.text == "ok"
    assert result.usage is not None and result.usage.nano == 4_900_000_000


def test_reasoning_picks_the_nearest_level_the_model_accepts(monkeypatch):
    from ov.agent.integrations import copilot

    monkeypatch.setattr(
        copilot,
        "list_models",
        lambda: [
            {"id": "big", "reasoning": ["low", "medium", "high", "xhigh", "max"]},
            {"id": "mini", "reasoning": ["low", "medium", "high"]},
            {"id": "old", "reasoning": []},
        ],
    )
    assert copilot.reasoning_for("big", "max") == "max"
    assert copilot.reasoning_for("mini", "max") == "high"
    assert copilot.reasoning_for("mini", "none") == "low"
    assert copilot.reasoning_for("old", "high") is None
    assert copilot.reasoning_for("big", "") is None
    with pytest.raises(ValueError):
        db.save_preferences({"reasoning": "huge"})
    assert db.save_preferences({"reasoning": "xhigh"})["reasoning"] == "xhigh"


def test_chat_retries_a_dropped_connection_before_any_text(monkeypatch):
    from ov.agent.engine.cancel import Cancel
    from ov.agent.integrations import copilot

    calls = []

    def flaky(api, headers, payload, cancel, on_text):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadError("connection reset")
        on_text("hi")
        return "ok"

    monkeypatch.setattr(copilot, "_headers", lambda **_: ("https://api", {}))
    monkeypatch.setattr(copilot, "_stream_once", flaky)
    monkeypatch.setattr(copilot, "RETRY_BASE_SECONDS", 0)
    assert copilot.stream_chat("m", [], [], "agent", cancel=Cancel(), on_text=lambda _: None) == "ok"
    assert len(calls) == 2


def test_chat_does_not_retry_after_text_streamed(monkeypatch):
    from ov.agent.engine.cancel import Cancel
    from ov.agent.integrations import copilot

    def dropped(api, headers, payload, cancel, on_text):
        on_text("partial")
        raise httpx.ReadError("connection reset")

    monkeypatch.setattr(copilot, "_headers", lambda **_: ("https://api", {}))
    monkeypatch.setattr(copilot, "_stream_once", dropped)
    with pytest.raises(copilot.CopilotError, match="Lost the connection"):
        copilot.stream_chat("m", [], [], "agent", cancel=Cancel(), on_text=lambda _: None)
