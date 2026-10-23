from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from typing_extensions import override

from ov.agent.engine import compaction
from ov.agent.engine.cancel import Cancel
from ov.agent.integrations import copilot
from ov.agent.integrations.common import Usage
from ov.agent.providers import copilot_turn
from ov.agent.providers.base import AgentProvider, CostUnit, Initiator

if TYPE_CHECKING:
    from ov.agent.engine.run import Run

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


class CopilotProvider(AgentProvider):
    id = "copilot"
    name = "GitHub Copilot"
    cost_unit = CostUnit.CREDITS
    cache_ttl_ms = None
    errors = (copilot.CopilotError, copilot_turn.CompactionError)

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

    @override
    def supports_vision(self, model: str) -> bool:
        return copilot.supports_vision(model)

    @override
    def complete(self, model: str, system: str, user_text: str, max_tokens: int) -> tuple[str, Usage | None]:
        return copilot.complete(model, system, user_text, max_tokens)

    @override
    def summarize(self, model: str, transcript: str) -> tuple[str, Usage | None]:
        return copilot.complete(
            model,
            compaction.SUMMARY_PROMPT,
            transcript,
            compaction.SUMMARY_MAX_TOKENS,
            copilot_turn.SUMMARY_READ_TIMEOUT_SECONDS,
        )

    @override
    def run_turn(self, run: Run, initiator: Initiator) -> None:
        copilot_turn.run_turn(run, initiator)

    @override
    def has_context(self, run: Run) -> bool:
        return copilot_turn.has_context(run)

    @override
    def compact(self, run: Run) -> None:
        copilot_turn.summarize(run, run.model, "manual")

    @override
    def drive_browser(self, run: Run, model: str, goal: str, cancel: Cancel) -> str:
        return copilot_turn.drive_browser(run, model, goal, cancel)

    @override
    def retry_anchor(self, run: Run, item_id: str) -> dict[str, Any] | None:
        return None

    @override
    def forget_thread(self, events: list[dict[str, Any]], folder: str) -> None:
        return None

    @override
    def close(self) -> None:
        return None
