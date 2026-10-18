from __future__ import annotations

import re
from typing import Any

from ov.agent.integrations import claude, copilot
from ov.agent.integrations.copilot import Usage
from ov.agent.storage.models import Provider

CLAUDE_FAST = "haiku"
CLAUDE_MODELS = ("opus", CLAUDE_FAST)
COPILOT_PREFERRED = re.compile(r"^claude-opus-(\d+(?:\.\d+)?)$")
COPILOT_FAST = re.compile(r"^claude-haiku-(\d+(?:\.\d+)?)$")


def list_models(provider: Provider) -> list[dict[str, Any]]:
    if provider == Provider.CLAUDE:
        return claude.list_models()
    return copilot.list_models()


def complete(provider: Provider, model: str, system: str, user_text: str, max_tokens: int) -> tuple[str, Usage | None]:
    if provider == Provider.CLAUDE:
        return claude.complete(model, system, user_text)
    return copilot.complete(model, system, user_text, max_tokens)


def supports_vision(provider: Provider, model: str) -> bool:
    if provider == Provider.CLAUDE:
        return True
    return copilot.supports_vision(model)


def signed_in(provider: Provider) -> bool:
    if provider == Provider.CLAUDE:
        return bool(claude.account()["signedIn"])
    return bool(copilot.user())


def _version(pattern: re.Pattern[str], model_id: str) -> float:
    found = pattern.match(model_id)
    return float(found.group(1)) if found else -1.0


def _newest(listed: list[dict[str, Any]], pattern: re.Pattern[str]) -> str:
    return str(max(listed, key=lambda m: _version(pattern, m["id"]))["id"])


def default_models(provider: Provider) -> tuple[str | None, str | None]:
    if provider == Provider.CLAUDE:
        return CLAUDE_MODELS

    if copilot.user() is None:
        return None, None

    listed = copilot.list_models()
    if not listed:
        raise copilot.CopilotError("Copilot offers no models to this account.")

    fast = _newest(listed, COPILOT_FAST)
    return _newest(listed, COPILOT_PREFERRED), fast if COPILOT_FAST.match(fast) else None
