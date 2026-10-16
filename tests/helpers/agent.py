from __future__ import annotations

import time
from pathlib import Path

from ov.agent.engine.cancel import Cancel
from ov.agent.engine.guard import Effect, Verdict
from ov.agent.engine.run import runs
from ov.agent.storage import db
from ov.agent.tools.base import APPROVE, Approval

RUN_POLLS = 100
RUN_POLL_SECONDS = 0.05


class ClosedBrowser:
    live = False


class FakeContext:
    def __init__(
        self,
        work_dir: Path,
        write: bool = False,
        approve: str = "Approve",
        note: str = "",
        effects: dict[str, Effect] | None = None,
        *,
        auto: bool = False,
        full: bool = False,
        risky: bool = False,
    ) -> None:
        self.work_dir = work_dir
        self.cancel = Cancel()
        self.vision = True
        self.instance = "acme"
        self.opened: set[str] = set()
        self.events: list[dict] = []
        self.asked: list[str] = []
        self.edits: list[tuple] = []
        self.write = write
        self.approve = approve
        self.note = note
        self.reasons: list[str] = []
        self.effects = effects or {}
        self.judged: list[str] = []
        self.auto = auto
        self.full = full
        self.risky = risky
        self.browser = ClosedBrowser()

    def emit(self, event):
        self.events.append(event)

    def has_outcome(self):
        return False

    def ask_user(self, items):
        self.asked += [item["question"] for item in items]
        return [self.approve for _ in items]

    def ask_approval(self, question, detail, reason=""):
        self.asked.append(detail)
        self.reasons.append(reason)
        return Approval(self.approve == APPROVE, self.note)

    def require_login(self, host):
        return False

    def attach_image(self, name, url):
        pass

    def record_edit(self, path, before, after, created):
        self.edits.append((path, before, after, created))

    def finish(self, outcome):
        pass

    def can_write(self):
        return self.write

    def auto_approves(self):
        return self.auto

    def full_access(self):
        return self.full

    def judge_risk(self, change):
        self.judged.append(change)
        return Verdict(Effect.RISKY if self.risky else Effect.ROUTINE, "it deletes data")

    def judge_command(self, command, folder):
        self.judged.append(command)
        effect = self.effects.get(command, Effect.READ)
        return Verdict(effect, f"it is {effect.value}")


def wait_done(run):
    for _ in range(RUN_POLLS):
        if run.state["summary"]["status"] in ("done", "error"):
            break
        time.sleep(RUN_POLL_SECONDS)
    assert run.state["summary"]["status"] == "done", run.state.get("error")


def isolated_agent_db(monkeypatch):
    monkeypatch.setattr("ov.agent.integrations.copilot.complete", lambda *a, **k: ("Test thread", None))
    db.close()
    yield
    runs.close()
    db.close()


def workspace_folder(tmp_path: Path):
    folder = tmp_path / "code"
    (folder / "module" / "node_modules").mkdir(parents=True)
    (folder / "module" / "main.py").write_text("alpha\nRULE_ID = 1\n", encoding="utf-8")
    (folder / "module" / "node_modules" / "skip.js").write_text("RULE_ID", encoding="utf-8")
    db.save_preferences({"workspace": str(folder)})
    yield folder
    db.save_preferences({"workspace": ""})
