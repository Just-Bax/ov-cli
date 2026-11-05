from __future__ import annotations

from typing import TYPE_CHECKING, Any

from typing_extensions import override

from ov.agent.engine.cancel import Cancel
from ov.agent.integrations import claude
from ov.agent.integrations.common import Usage
from ov.agent.providers import claude_session
from ov.agent.providers.base import AgentProvider, CostUnit, Initiator

if TYPE_CHECKING:
    from ov.agent.engine.run import Run

DEFAULT_MODEL = "opus"
FAST_MODEL = "haiku"
CACHE_TTL_MS = 60 * 60_000
SUMMARY_TIMEOUT_SECONDS = 300
NEVER_SENT = "This message never reached Claude, so it cannot be retried."


class ClaudeProvider(AgentProvider):
    id = "claude"
    name = "Claude"
    cost_unit = CostUnit.USD
    cache_ttl_ms = CACHE_TTL_MS
    errors = (claude.ClaudeError,)

    @override
    def account(self) -> dict[str, Any]:
        return claude.account()

    @override
    def list_models(self) -> list[dict[str, Any]]:
        return claude.list_models()

    @override
    def default_models(self) -> tuple[str | None, str | None]:
        return DEFAULT_MODEL, FAST_MODEL

    @override
    def helper_model(self, chosen: str) -> str:
        return chosen or FAST_MODEL

    @override
    def complete(self, model: str, system: str, user_text: str, max_tokens: int) -> tuple[str, Usage | None]:
        return claude.complete(model, system, user_text)

    @override
    def summarize(self, model: str, prompt: str, transcript: str) -> tuple[str, Usage | None]:
        return claude.complete(model, prompt, transcript, SUMMARY_TIMEOUT_SECONDS)

    @override
    def run_turn(self, run: Run, initiator: Initiator) -> None:
        claude_session.run_turn(run)

    @override
    def has_context(self, run: Run) -> bool:
        return run.state["session"]["id"] is not None

    @override
    def compact(self, run: Run) -> None:
        claude_session.compact(run)

    @override
    def drive_browser(self, run: Run, model: str, goal: str, cancel: Cancel) -> str:
        return claude_session.drive_browser(run, model, goal, cancel)

    @override
    def retry_anchor(self, run: Run, item_id: str) -> dict[str, Any] | None:
        anchor = run.state["session"]["turns"].get(item_id)
        if anchor is None:
            raise claude.ClaudeError(NEVER_SENT)
        return anchor

    @override
    def branch_context(self, source: Run, child: Run, before: str | None) -> None:
        session, up_to = claude_session.branch_anchor(source, before)
        forked = claude_session.fork_into(session, up_to, child.work_dir) if session and up_to else None
        child.emit({"type": "meta", "session": {"id": forked, "spent": 0.0}})

    @override
    def forget_thread(self, events: list[dict[str, Any]], folder: str) -> None:
        claude_session.forget_sessions(claude_session.sessions_of(events), folder)

    @override
    def close(self) -> None:
        claude.close_helpers()
