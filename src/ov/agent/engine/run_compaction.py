from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ov.agent.engine import compaction
from ov.agent.engine.prompt import system_prompt
from ov.agent.engine.run_common import RunError, uid
from ov.agent.engine.state import question_text
from ov.agent.storage import db
from ov.agent.storage.models import UsageKind

NOTHING_TO_COMPACT = "There is nothing to compact in this thread yet."
COMPACT_WHILE_BUSY = "Wait for the agent to finish, or stop it, before compacting."
CONTINUED_CONTEXT = (
    '[This thread continues the earlier thread "{title}". The summary below is everything carried over from it; '
    "the user's next message says what to do now.]\n\n{summary}"
)
CONTINUED_MESSAGE = "Continued from **{title}**. This is what carries over:\n\n{summary}"
CONTINUE_TRANSCRIPT_CHARS = 400_000
HISTORY_USER = "User:"
HISTORY_AGENT = "Agent:"
HISTORY_GAP = "[The middle of the thread is left out to keep this short.]"
SUMMARY_EMPTY = "{model} returned an empty summary."


class CompactionMixin:
    def record_context(self, tokens: int, limit: int, compact_at: int | None) -> None:
        context = {"tokens": tokens, "limit": limit, **({"compactAt": compact_at} if compact_at else {})}
        if self.state.get("context") != context:
            self.emit({"type": "context", "context": context})

    def compact(self) -> None:
        if not self.agent.has_context(self):
            raise RunError(NOTHING_TO_COMPACT)
        if not self._claim():
            raise RunError(COMPACT_WHILE_BUSY)

        self._spawn(self._compact_now)

    def _compact_now(self) -> None:
        try:
            self._set_status("running")
            self.agent.compact(self)
            self._set_status("done")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._busy = False
            self._mark_stable()
            self._pick_up_queue()

    def compaction_started(self, trigger: str) -> None:
        with self._lock:
            if self._compacting is not None:
                return
            self._compacting = {"id": uid("k"), "trigger": trigger, "status": "running", "startedAt": db.now_ms()}
            entry = dict(self._compacting)
        self.emit({"type": "compact", "compact": entry})

    def compaction_finished(self, trigger: str, before: int, after: int) -> None:
        with self._lock:
            entry, self._compacting = self._compacting or {"id": uid("k"), "startedAt": db.now_ms()}, None
        done = {**entry, "trigger": trigger, "status": "done", "before": before, "after": after}
        self.emit({"type": "compact", "compact": {**done, "ms": db.now_ms() - entry["startedAt"]}})

    def compaction_failed(self, error: str) -> None:
        with self._lock:
            entry, self._compacting = self._compacting, None
        if entry is not None:
            self.emit({"type": "compact", "compact": {**entry, "status": "error", "error": error}})

    def history_text(self, start: int = 0) -> str:
        with self._lock:
            lines = [_history_line(self.state, item) for item in self.state["items"][start:]]
        text = "\n\n".join(line for line in lines if line)
        if len(text) <= CONTINUE_TRANSCRIPT_CHARS:
            return text

        first = next((line for line in lines if line.startswith(HISTORY_USER)), "")
        return f"{first}\n\n{HISTORY_GAP}\n\n{text[-CONTINUE_TRANSCRIPT_CHARS:]}"

    def carry_over(self, source_title: str, history: str) -> None:
        self._busy = True
        self._spawn(self._carry_over, source_title, history)

    def _summary_of(self, history: str) -> str:
        summary, usage = self.agent.summarize(
            self.model, compaction.SUMMARY_PROMPT, f"<conversation>\n{history}\n</conversation>"
        )
        self.record_usage(self.model, UsageKind.SUMMARY, usage)
        if not summary.strip():
            raise RunError(SUMMARY_EMPTY.format(model=self.model))
        return summary

    def _carry_over(self, source_title: str, history: str) -> None:
        try:
            self._set_status("running")
            summary = self._summary_of(history)
            carried = CONTINUED_CONTEXT.format(title=source_title, summary=summary)
            self.messages = [
                {"role": "system", "content": system_prompt(self.access, self.instance)},
                {"role": "user", "content": carried},
            ]
            self.persist()

            shown = CONTINUED_MESSAGE.format(title=source_title, summary=summary)
            self.emit({"type": "agent_message", "messageId": self.new_message_id(), "text": shown, "ts": db.now_ms()})
            self._set_status("done")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._busy = False
            self._mark_stable()
            self._pick_up_queue()


def _found(entries: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((e for e in entries if e["id"] == item_id), None)


def _chat_line(state: dict[str, Any], item_id: str, speaker: str) -> str:
    message = _found(state["chat"], item_id)
    return f"{speaker}\n{message['text']}" if message and message["text"].strip() else ""


def _tool_line(state: dict[str, Any], item_id: str) -> str:
    tool = _found(state["tools"], item_id)
    if tool is None:
        return ""
    output = (tool.get("output") or "")[: compaction.TRANSCRIPT_TOOL_CHARS]
    return f"Agent called {tool['name']} ({tool.get('label') or ''}):\n{output}"


def _question_line(state: dict[str, Any], item_id: str) -> str:
    question = _found(state["questions"], item_id)
    return f"Agent asked: {question_text(question)}" if question else ""


def _branch_result_line(state: dict[str, Any], item_id: str) -> str:
    result = _found(state["branchResults"], item_id)
    return f"Brought back from the branch {result['branch']['title']}:\n{result['text']}" if result else ""


def _outcome_line(state: dict[str, Any], _item_id: str) -> str:
    outcome = state.get("outcome")
    return f"{HISTORY_AGENT}\n{outcome.get('reply') or ''}" if outcome else ""


_HISTORY_LINES: dict[str, Callable[[dict[str, Any], str], str]] = {
    "user": lambda state, item_id: _chat_line(state, item_id, HISTORY_USER),
    "text": lambda state, item_id: _chat_line(state, item_id, HISTORY_AGENT),
    "tool": _tool_line,
    "question": _question_line,
    "branch_result": _branch_result_line,
    "outcome": _outcome_line,
}


def _history_line(state: dict[str, Any], item: dict[str, Any]) -> str:
    line = _HISTORY_LINES.get(item["kind"])
    return line(state, item["id"]) if line else ""
