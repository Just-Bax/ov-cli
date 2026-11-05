from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from typing_extensions import override

from ov.agent.engine import compaction
from ov.agent.engine.cancel import Cancel
from ov.agent.integrations.common import Usage
from ov.agent.providers import chat_turn
from ov.agent.providers.base import AgentProvider, Initiator

if TYPE_CHECKING:
    from ov.agent.engine.run import Run


class ChatProvider(AgentProvider):
    backend: ClassVar[chat_turn.ChatBackend]
    helper_read_timeout: ClassVar[float]
    cache_ttl_ms = None

    @override
    def supports_vision(self, model: str) -> bool:
        return self.backend.supports_vision(model)

    @override
    def complete(self, model: str, system: str, user_text: str, max_tokens: int) -> tuple[str, Usage | None]:
        return self.backend.complete(model, system, user_text, max_tokens, self.helper_read_timeout)

    @override
    def summarize(self, model: str, prompt: str, transcript: str) -> tuple[str, Usage | None]:
        return self.backend.complete(
            model,
            prompt,
            transcript,
            compaction.SUMMARY_MAX_TOKENS,
            chat_turn.SUMMARY_READ_TIMEOUT_SECONDS,
        )

    @override
    def run_turn(self, run: Run, initiator: Initiator) -> None:
        chat_turn.run_turn(self.backend, run, initiator)

    @override
    def has_context(self, run: Run) -> bool:
        return chat_turn.has_context(run)

    @override
    def compact(self, run: Run) -> None:
        chat_turn.summarize(self.backend, run, run.model, "manual")

    @override
    def drive_browser(self, run: Run, model: str, goal: str, cancel: Cancel) -> str:
        return chat_turn.drive_browser(self.backend, run, model, goal, cancel)

    @override
    def retry_anchor(self, run: Run, item_id: str) -> dict[str, Any] | None:
        return None

    @override
    def branch_context(self, source: Run, child: Run, before: str | None) -> None:
        return None

    @override
    def forget_thread(self, events: list[dict[str, Any]], folder: str) -> None:
        return None

    @override
    def close(self) -> None:
        return None
