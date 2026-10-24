from __future__ import annotations

from collections.abc import Callable

from ov.agent import workspace as project
from ov.agent.engine import guard
from ov.agent.integrations.common import Usage
from ov.agent.storage.models import Access, UsageKind


class GuardMixin:
    def has_outcome(self) -> bool:
        return bool(self.state.get("outcome"))

    def can_write(self) -> bool:
        return self.access != Access.READ

    def auto_approves(self) -> bool:
        return self.access == Access.AUTO

    def full_access(self) -> bool:
        return self.access == Access.FULL

    def judge_command(self, command: str, folder: str) -> guard.Verdict:
        return self._judged(
            (command, folder),
            lambda model: guard.judge(self.agent, model, command, folder, project.shell_name()),
        )

    def judge_page_action(self, action: str) -> guard.Verdict:
        return self._judged(("page", action), lambda model: guard.judge_page_action(self.agent, model, action))

    def judge_risk(self, change: str) -> guard.Verdict:
        return self._judged(("risk", change), lambda model: guard.judge_risk(self.agent, model, change), shown=False)

    def _judged(
        self,
        key: tuple[str, ...],
        ask: Callable[[str], tuple[guard.Verdict, Usage | None]],
        shown: bool = True,
    ) -> guard.Verdict:
        with self._lock:
            verdict = self._verdicts.get(key)
        if verdict is None:
            model = self._helper_model()
            verdict, usage = ask(model)
            self.record_usage(model, UsageKind.GUARD, usage)
            with self._lock:
                self._verdicts[key] = verdict

        if shown:
            self.emit({"type": "tool", "tool": {"id": self._local.tool, "verdict": verdict.as_dict()}})
        return verdict
