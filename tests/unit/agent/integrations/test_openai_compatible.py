from __future__ import annotations

import httpx
import pytest

from ov.agent import providers
from ov.agent.integrations import openai_compatible
from ov.agent.integrations.common import Usage
from ov.agent.integrations.openai_compatible import OpenAICompatibleError
from ov.agent.storage.db import NANO_PER_UNIT

BASE_URL = "http://gpu-box:8000/v1"
SERVED = {
    "data": [
        {"id": "qwen3", "owned_by": "vllm", "max_model_len": 131_072},
        {"id": "tiny", "owned_by": "vllm", "max_model_len": 8192},
        {"id": "bare", "owned_by": "vllm"},
    ]
}


@pytest.fixture
def server(monkeypatch):
    seen: list[httpx.Request] = []

    def get(url, headers, timeout):
        request = httpx.Request("GET", url, headers=headers)
        seen.append(request)
        if not url.startswith(BASE_URL):
            return httpx.Response(404, request=request)
        return httpx.Response(200, json=SERVED, request=request)

    monkeypatch.setattr(openai_compatible.httpx, "get", get)
    openai_compatible._forget_models()
    yield seen
    openai_compatible._forget_models()


def test_connecting_checks_the_server_and_lists_its_models(ov_home, server):
    assert openai_compatible.account() == {"signedIn": False, "baseUrl": None, "hasKey": False}

    assert openai_compatible.connect(f" {BASE_URL}/ ", "sk-local") == {
        "signedIn": True,
        "baseUrl": BASE_URL,
        "hasKey": True,
    }
    assert server[-1].headers["Authorization"] == "Bearer sk-local"
    assert [m["id"] for m in openai_compatible.list_models()] == ["qwen3", "tiny", "bare"]
    assert openai_compatible.token_limits("qwen3") == (131_072, 131_072, openai_compatible.OUTPUT_RESERVE_TOKENS)
    assert providers.get("openai").default_models() == ("qwen3", "qwen3")


def test_a_wrong_base_url_is_explained(ov_home, server):
    with pytest.raises(OpenAICompatibleError, match="must start with http"):
        openai_compatible.connect("gpu-box:8000/v1", "")
    with pytest.raises(OpenAICompatibleError, match="usually ends with /v1"):
        openai_compatible.connect("http://elsewhere:8000", "")
    assert not openai_compatible.account()["signedIn"]


def test_models_without_a_usable_context_window_are_refused(ov_home, server):
    openai_compatible.connect(BASE_URL, "")
    with pytest.raises(OpenAICompatibleError, match="Set its context window"):
        openai_compatible.token_limits("bare")
    with pytest.raises(OpenAICompatibleError, match="needs at least"):
        openai_compatible.token_limits("tiny")


def test_per_model_settings_survive_reconnecting_to_the_same_server(ov_home, server):
    openai_compatible.connect(BASE_URL, "")

    listed = openai_compatible.configure_model("bare", vision=True, context_window=65_536)
    bare = next(m for m in listed if m["id"] == "bare")
    assert (bare["vision"], bare["windowTokens"], bare["reportedWindow"]) == (True, 65_536, None)
    assert openai_compatible.supports_vision("bare") and not openai_compatible.supports_vision("qwen3")

    openai_compatible.connect(BASE_URL, "")
    assert openai_compatible.token_limits("bare")[0] == 65_536
    with pytest.raises(OpenAICompatibleError, match="does not serve gone"):
        openai_compatible.configure_model("gone", vision=False, context_window=None)
    with pytest.raises(OpenAICompatibleError, match="at least"):
        openai_compatible.configure_model("bare", vision=False, context_window=4096)


def test_usage_is_counted_in_tokens():
    body = {"usage": {"prompt_tokens": 1200, "completion_tokens": 80, "prompt_tokens_details": {"cached_tokens": 1000}}}
    assert openai_compatible.usage_of({"choices": []}) is None
    assert openai_compatible.usage_of(body) == Usage(
        tokens={"input": 200, "cache_read": 1000, "output": 80}, nano=1280 * NANO_PER_UNIT
    )


def test_nothing_works_until_connected(ov_home, server):
    with pytest.raises(OpenAICompatibleError, match="not connected"):
        openai_compatible.list_models()
    assert providers.get("openai").default_models() == (None, None)


def test_a_reply_without_usage_is_refused(ov_home, server, monkeypatch):
    from ov.agent.engine.cancel import Cancel
    from ov.agent.integrations import chat_completions
    from ov.agent.integrations.chat_completions import StreamResult

    openai_compatible.connect(BASE_URL, "")
    monkeypatch.setattr(chat_completions, "stream", lambda *a, **k: StreamResult(text="hi"))

    with pytest.raises(OpenAICompatibleError, match="no token usage"):
        openai_compatible.stream_chat("qwen3", [], [], "user", cancel=Cancel(), on_text=lambda _: None)
