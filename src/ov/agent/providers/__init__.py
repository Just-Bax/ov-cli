from __future__ import annotations

from ov.agent.providers.base import AgentProvider, ModelUnavailable
from ov.agent.providers.claude import ClaudeProvider
from ov.agent.providers.copilot import CopilotProvider

REGISTERED: dict[str, AgentProvider] = {p.id: p for p in (ClaudeProvider(), CopilotProvider())}


class UnknownProvider(ValueError):
    def __init__(self, provider_id: str) -> None:
        super().__init__(f"Unknown provider: {provider_id}. Use one of: {', '.join(REGISTERED)}.")


def get(provider_id: str) -> AgentProvider:
    found = REGISTERED.get(provider_id)
    if found is None:
        raise UnknownProvider(provider_id)
    return found


def every() -> list[AgentProvider]:
    return list(REGISTERED.values())


def errors() -> tuple[type[Exception], ...]:
    return (ModelUnavailable, *(error for provider in REGISTERED.values() for error in provider.errors))


def close_all() -> None:
    for provider in REGISTERED.values():
        provider.close()
