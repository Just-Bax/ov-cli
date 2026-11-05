from __future__ import annotations

from ov.agent.engine.run_common import RunError, uid
from ov.agent.storage import db

NOTHING_TO_COMPACT = "There is nothing to compact in this thread yet."
COMPACT_WHILE_BUSY = "Wait for the agent to finish, or stop it, before compacting."


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
