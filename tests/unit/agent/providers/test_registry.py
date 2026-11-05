from __future__ import annotations

import pytest

from ov.agent import providers
from ov.agent.integrations import claude, copilot
from ov.agent.providers.base import AgentProvider, CostUnit, ModelUnavailable


def test_every_provider_is_registered_by_its_id():
    listed = providers.every()

    assert [p.id for p in listed] == ["claude", "copilot", "openai"]
    assert all(isinstance(p, AgentProvider) for p in listed)
    assert providers.get("claude").cost_unit == CostUnit.USD
    assert providers.get("copilot").cost_unit == CostUnit.CREDITS
    assert providers.get("openai").cost_unit == CostUnit.TOKENS
    with pytest.raises(providers.UnknownProvider, match="Use one of: claude, copilot, openai"):
        providers.get("nope")


def test_provider_errors_are_shown_to_the_user():
    errors = providers.errors()
    assert {ModelUnavailable, claude.ClaudeError, copilot.CopilotError} <= set(errors)


def test_a_provider_describes_itself_for_the_app(monkeypatch):
    monkeypatch.setattr("ov.agent.integrations.copilot.user", lambda: "someone")

    described = providers.get("copilot").describe()

    assert described == {
        "id": "copilot",
        "name": "GitHub Copilot",
        "costUnit": "credits",
        "cacheTtlMs": None,
        "account": {"signedIn": True, "user": "someone"},
    }


def test_only_the_claude_cache_expires(monkeypatch):
    assert providers.get("claude").cache_ttl_ms == 60 * 60_000
    assert providers.get("copilot").cache_ttl_ms is None


def test_an_unknown_model_names_the_provider(monkeypatch):
    monkeypatch.setattr("ov.agent.integrations.claude.list_models", lambda: [{"id": "opus", "vision": True}])
    assert providers.get("claude").supports_vision("opus")
    with pytest.raises(ModelUnavailable, match="Model sonnet is not available on Claude"):
        providers.get("claude").supports_vision("sonnet")


def test_copilot_hides_models_it_cannot_call_through_chat_completions():
    def model(endpoints):
        entry = {
            "id": "m",
            "capabilities": {"type": "chat", "supports": {"tool_calls": True}, "limits": {}},
        }
        return entry if endpoints is None else {**entry, "supported_endpoints": endpoints}

    assert copilot._usable(model(["/v1/messages", "/chat/completions"]))
    assert copilot._usable(model(None))
    assert not copilot._usable(model(["/responses", "ws:/responses"]))


def test_copilot_needs_every_token_limit_to_compact(monkeypatch):
    listed = {"id": "m", "contextWindow": 200_000, "windowTokens": 264_000, "outputTokens": None}
    monkeypatch.setattr("ov.agent.integrations.copilot.list_models", lambda: [listed])
    with pytest.raises(copilot.CopilotError, match="does not say how much context m takes"):
        copilot.token_limits("m")
    listed["outputTokens"] = 64_000
    assert copilot.token_limits("m") == (264_000, 200_000, 64_000)
