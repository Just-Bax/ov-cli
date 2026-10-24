from __future__ import annotations

import re
from typing import Any

from typing_extensions import override

from ov.agent.integrations import copilot
from ov.agent.providers import chat_turn
from ov.agent.providers.base import CostUnit
from ov.agent.providers.chat import ChatProvider

PREFERRED_MODEL = re.compile(r"^claude-opus-(\d+(?:\.\d+)?)$")
FAST_MODEL = re.compile(r"^claude-haiku-(\d+(?:\.\d+)?)$")
NO_FAST_MODEL = (
    "No fast model is set for Copilot. Pick one in Settings; titles, change checks and the browser run on it."
)


def _version(pattern: re.Pattern[str], model_id: str) -> float:
    found = pattern.match(model_id)
    return float(found.group(1)) if found else -1.0


def _newest(listed: list[dict[str, Any]], pattern: re.Pattern[str]) -> str:
    return str(max(listed, key=lambda m: _version(pattern, m["id"]))["id"])


class CopilotProvider(ChatProvider):
    id = "copilot"
    name = "GitHub Copilot"
    cost_unit = CostUnit.CREDITS
    errors = (copilot.CopilotError, chat_turn.CompactionError)
    backend = copilot
    helper_read_timeout = copilot.HTTP_TIMEOUT_SECONDS

    @override
    def account(self) -> dict[str, Any]:
        user = copilot.user()
        return {"signedIn": bool(user), "user": user}

    @override
    def list_models(self) -> list[dict[str, Any]]:
        return copilot.list_models()

    @override
    def default_models(self) -> tuple[str | None, str | None]:
        if copilot.user() is None:
            return None, None

        listed = copilot.list_models()
        if not listed:
            raise copilot.CopilotError("Copilot offers no models to this account.")

        fast = _newest(listed, FAST_MODEL)
        return _newest(listed, PREFERRED_MODEL), fast if FAST_MODEL.match(fast) else None

    @override
    def helper_model(self, chosen: str) -> str:
        if not chosen:
            raise copilot.CopilotError(NO_FAST_MODEL)
        return chosen
