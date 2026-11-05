from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ov.agent.engine.run_common import RunError
from ov.agent.storage import db

NOTHING_FINISHED = "Nothing in this thread has finished yet, so there is nothing to branch from."
NOT_A_TURN = "That message does not start a turn in this thread, so it cannot be branched from."
STILL_RUNNING = "That message is part of the turn still running. Branch from an earlier one, or wait for it to finish."
INHERITED_RETRY = "That message came from the thread this one branched from. Use Retry as branch on it instead."
INHERITED_RUNNING = "Still running in the parent thread when this branch was made, so its result is not here."
BRANCH_BUSY = "The new branch is still starting. Try again in a moment."
INHERITED_REVERT = (
    "This data change was made in the thread this one branched from. Revert it there, so it is not undone twice."
)


@dataclass(frozen=True)
class BranchPoint:
    before: str | None
    messages: int
    until: int
    last_turn: str | None


class BranchMixin:
    _stable: BranchPoint | None

    def _point_after_all(self) -> BranchPoint:
        with self._lock:
            count = len(self.messages)
            return BranchPoint(None, count, self.seq + 1, self._last_turn(count))

    def _last_turn(self, messages: int) -> str | None:
        earlier = sorted((index, turn) for turn, index in self.turns.items() if index < messages)
        return earlier[-1][1] if earlier else None

    def _mark_stable(self) -> None:
        point = self._point_after_all()
        with self._lock:
            self._stable = point

    def branch_point(self, before: str | None) -> BranchPoint:
        with self._lock:
            busy, stable = self._busy, self._stable
        if before is None and not busy:
            self.persist()
            return self._point_after_all()

        if before is None:
            if stable is None:
                raise RunError(NOTHING_FINISHED)
            return stable

        self.persist()
        index = self.turns.get(before)
        if index is None:
            raise RunError(NOT_A_TURN)
        if busy and (stable is None or index > stable.messages):
            raise RunError(STILL_RUNNING)

        until = db.turn_event_position(self.id, before)
        if until is None:
            raise RunError(NOT_A_TURN)
        return BranchPoint(before, index, until, self._last_turn(index))

    def inherited_item(self, item_id: str) -> bool:
        with self._lock:
            inherited = self.state.get("inheritedItems", 0)
            return any(x["id"] == item_id for x in self.state["items"][:inherited])

    def name_branch(self, text: str) -> None:
        with self._lock:
            inherited = self.state.get("inheritedItems", 0)
            own_turns = any(x["kind"] == "user" for x in self.state["items"][inherited:])
        if self.state["summary"].get("origin") == "branch" and not own_turns and text.strip():
            self._name_later(text)

    def resend(self, message: dict[str, Any], content: Any) -> None:
        if not self._claim():
            raise RunError(BRANCH_BUSY)
        self.name_branch(message["text"])
        self.emit({"type": "user_message", "message": {**message, "ts": db.now_ms()}})
        self._push_turn(message["id"], content)
        self._spawn(self._run_turn)

    def settle_inherited(self) -> None:
        with self._lock:
            running = [t["id"] for t in self.state["tools"] if t["status"] == "running"]
        for tool_id in running:
            self.emit({"type": "tool", "tool": {"id": tool_id, "status": "error", "output": INHERITED_RUNNING}})
        self._set_status("done")
        self._mark_stable()
