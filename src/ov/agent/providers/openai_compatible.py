from __future__ import annotations

from typing import Any

from typing_extensions import override

from ov.agent.integrations import openai_compatible
from ov.agent.providers import chat_turn
from ov.agent.providers.base import CostUnit
from ov.agent.providers.chat import ChatProvider

NO_FAST_MODEL = "No fast model is set. Pick one in Settings; titles, change checks and the browser run on it."


class OpenAICompatibleProvider(ChatProvider):
    id = "openai"
    name = openai_compatible.NAME
    cost_unit = CostUnit.TOKENS
    errors = (openai_compatible.OpenAICompatibleError, chat_turn.CompactionError)
    backend = openai_compatible
    helper_read_timeout = chat_turn.SUMMARY_READ_TIMEOUT_SECONDS

    @override
    def account(self) -> dict[str, Any]:
        return openai_compatible.account()

    @override
    def list_models(self) -> list[dict[str, Any]]:
        return openai_compatible.list_models()

    @override
    def default_models(self) -> tuple[str | None, str | None]:
        if not self.signed_in():
            return None, None
        first = openai_compatible.list_models()[0]["id"]
        return first, first

    @override
    def helper_model(self, chosen: str) -> str:
        if not chosen:
            raise openai_compatible.OpenAICompatibleError(NO_FAST_MODEL)
        return chosen
