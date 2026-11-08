from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ov.agent.engine.cancel import Cancel
from ov.agent.tools.base import Approval, ToolError

if TYPE_CHECKING:
    from ov.agent.engine.run import Run

NEEDS_USER = (
    "This needs the user's approval or sign-in, which a background task cannot ask for. Run it again in the foreground."
)


@dataclass
class Task:
    tool: dict[str, Any]
    started_at: int
    backgrounded_at: int | None = None
    stopped_at: int | None = None
    finished: bool = False
    result: str = ""
    cancel: Cancel = field(default_factory=Cancel)
    settled: threading.Event = field(default_factory=threading.Event)

    @property
    def id(self) -> str:
        return str(self.tool["id"])

    @property
    def label(self) -> str:
        return str(self.tool["label"])


class TaskContext:
    def __init__(self, run: Run, task: Task) -> None:
        self._run = run
        self._task = task

    @property
    def cancel(self) -> Cancel:
        return self._task.cancel

    def __getattr__(self, name: str) -> Any:
        return getattr(self._run, name)

    def ask_user(self, items: list[dict[str, Any]]) -> list[str]:
        self._require_foreground()
        return self._run.ask_user(items)

    def ask_approval(self, question: str, detail: str, reason: str = "") -> Approval:
        self._require_foreground()
        return self._run.ask_approval(question, detail, reason)

    def require_login(self, host: str, tenant: str = "", web: bool = False) -> bool:
        self._require_foreground()
        return self._run.require_login(host, tenant, web)

    def load_case(self, ref: str) -> str:
        return self._run.read_case(ref, self._task.cancel)

    def _require_foreground(self) -> None:
        if self._task.backgrounded_at is not None:
            raise ToolError(NEEDS_USER)
