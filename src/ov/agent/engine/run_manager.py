from __future__ import annotations

import random
import shutil
import string
import threading
from typing import Any

from ov.agent import providers
from ov.agent.engine.export import stored_state
from ov.agent.engine.feed import status_feed
from ov.agent.engine.files import run_dir
from ov.agent.engine.prompt import system_prompt
from ov.agent.engine.run import Run
from ov.agent.engine.run_branch import NOTHING_FINISHED
from ov.agent.engine.run_common import RunError
from ov.agent.engine.run_titles import TITLE_CHARS, short_title
from ov.agent.engine.state import empty_state
from ov.agent.storage import db
from ov.agent.storage.db import Lineage
from ov.agent.storage.models import Access, Origin
from ov.agent.tools.data_change import RECORD_SUFFIX

CONTINUE_WHILE_BUSY = "Wait for the agent to finish, or stop it, before continuing in a new thread."
NOTHING_TO_CONTINUE = "This thread has nothing to carry over yet."
CONTINUED_TITLE = "{title} (continued)"
BRANCH_TITLE = "{title} (branch)"
FINDINGS_TITLE = "{title} (from findings)"
NO_FINDINGS = "This thread has no findings yet. Save some first."
NOT_YOUR_TURN = "Pick one of your own messages to retry as a branch."
PARENT_GONE = "The thread this one came from is gone, so there is nowhere to bring the result back to."
FINDINGS_CONTEXT = (
    '[This thread starts from the findings of the earlier thread "{title}" ({id}). They were verified there; '
    "treat them as known and check again only what the user asks about. The user's next message says what to do "
    "now.]\n\n{findings}"
)
FINDINGS_MESSAGE = "Started from the findings of **{title}**:\n\n{findings}"
PROMPT_TITLE_CHARS = 60
RUN_ID_SUFFIX_CHARS = 4
BASE36_DIGITS = string.digits + string.ascii_lowercase
IDLE_EVICT_MS = 5 * 60_000
MAX_CACHED_RUNS = 6
EVICT_GRACE_MS = 60_000
FULL_ACCESS_NEEDS_FLAG = "Full access needs OV Agent started with: ov agent --full-access"
FULL_ACCESS_OFF_NOTE = (
    "Full access is off because OV Agent was started without --full-access. This run is now on Auto: only risky "
    "changes wait for the user's approval."
)


class RunManager:
    def __init__(self) -> None:
        self.full_access = False
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self._deleting: set[str] = set()

    def create(self, data: dict[str, Any], provider: str, model: str) -> Run:
        prompt = (data.get("prompt") or "").strip()
        title = short_title(prompt.split("\n", 1)[0], PROMPT_TITLE_CHARS) or "Attached files"
        access = Access(data["access"])
        run = self._new(title, provider=provider, model=model, instance=data.get("instance"), access=access)
        run.begin(data)
        return run

    def continue_in_new(self, run_id: str) -> Run:
        source = self.get(run_id)
        if source is None:
            raise RunError("No such thread.")
        if source.working():
            raise RunError(CONTINUE_WHILE_BUSY)

        history = source.history_text()
        if not history:
            raise RunError(NOTHING_TO_CONTINUE)

        run = self._new_from(source, CONTINUED_TITLE, Lineage(source.id, Origin.SUMMARY, None, 0))
        run.carry_over(source.state["summary"]["title"], history)
        return run

    def branch(self, run_id: str, before: str | None = None) -> Run:
        source = self._require(run_id)
        point = source.branch_point(before)
        if point.last_turn is None and before is None:
            raise RunError(NOTHING_FINISHED)

        child_id = _new_id()
        db.create_thread(
            child_id,
            short_title(BRANCH_TITLE.format(title=source.state["summary"]["title"]), TITLE_CHARS),
            source.provider,
            source.model,
            instance=source.instance or None,
            access=source.access,
            lineage=Lineage(source.id, Origin.BRANCH, point.last_turn, point.until),
        )

        try:
            db.copy_inherited(source.id, child_id, until=point.until, messages=point.messages)
            _copy_folder(source.id, child_id)
            child = self._require(child_id)
            source.agent.branch_context(source, child, point.before)
            child.settle_inherited()
        except Exception:
            self.delete(child_id)
            raise

        status_feed.publish({"kind": "list"})
        return child

    def retry_as_branch(self, run_id: str, item_id: str) -> Run:
        source = self._require(run_id)
        message = next((m for m in source.state["chat"] if m["id"] == item_id and m["role"] == "user"), None)
        if message is None or item_id not in source.turns:
            raise RunError(NOT_YOUR_TURN)
        content = source.messages[source.turns[item_id]]["content"]

        child = self.branch(run_id, item_id)
        child.resend(message, content)
        return child

    def aside(self, run_id: str, message_id: str, text: str, files: list[dict[str, str]]) -> Run:
        child = self.branch(run_id)
        child.follow_up(message_id, text, files, False)
        return child

    def bring_back(self, run_id: str, text: str) -> None:
        branch = self._require(run_id)
        parent_id = branch.state["summary"].get("parentId")
        parent = self.get(parent_id) if parent_id else None
        if parent is None:
            raise RunError(PARENT_GONE)

        parent.receive_branch_result({"id": branch.id, "title": branch.state["summary"]["title"]}, text)
        db.set_settled(parent.id, False)
        status_feed.publish({"kind": "list"})

    def from_findings(self, run_id: str) -> Run:
        source = self._require(run_id)
        findings = db.list_findings(source.id)
        if not findings:
            raise RunError(NO_FINDINGS)

        run = self._new_from(source, FINDINGS_TITLE, Lineage(source.id, Origin.FINDINGS, None, 0))
        db.copy_all_findings(source.id, run.id)
        title, listed = source.state["summary"]["title"], "\n".join(f"- {f['text']}" for f in findings)
        context = FINDINGS_CONTEXT.format(title=title, id=source.id, findings=listed)
        run.messages = [
            {"role": "system", "content": system_prompt(run.access, run.instance)},
            {"role": "user", "content": context},
        ]
        run.persist()

        shown = FINDINGS_MESSAGE.format(title=title, findings=listed)
        run.emit({"type": "agent_message", "messageId": run.new_message_id(), "text": shown, "ts": db.now_ms()})
        run.settle_inherited()
        return run

    def _require(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run is None:
            raise RunError("No such thread.")
        return run

    def _new_from(self, source: Run, title: str, lineage: Lineage) -> Run:
        run = self._new(
            short_title(title.format(title=source.state["summary"]["title"]), TITLE_CHARS),
            provider=source.provider,
            model=source.model,
            instance=source.instance or None,
            access=source.access,
            lineage=lineage,
        )
        run.state["parent"] = {"id": source.id, "title": source.state["summary"]["title"]}
        return run

    def _new(
        self,
        title: str,
        *,
        provider: str,
        model: str,
        instance: str | None,
        access: Access,
        lineage: Lineage | None = None,
    ) -> Run:
        providers.get(provider)
        run_id = _new_id()
        summary = db.create_thread(run_id, title, provider, model, instance=instance, access=access, lineage=lineage)

        run = Run(run_id, empty_state(summary, access), -1)
        with self._lock:
            self._runs[run_id] = run
        status_feed.publish({"kind": "list"})
        return run

    def resume_interrupted(self) -> None:
        for run_id in db.take_interrupted():
            run = self.get(run_id)
            if run is not None:
                run.resume_after_restart()

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            if run_id in self._deleting:
                return None
            live = self._runs.get(run_id)
            if live is not None:
                live.touched = db.now_ms()
                self._evict()
                return live

            stored = stored_state(run_id)
            if stored is None:
                return None

            state, seq = stored
            state.pop("browser", None)
            run = Run(run_id, state, seq)
            if run.access == Access.FULL and not self.full_access:
                run.set_access(Access.AUTO, FULL_ACCESS_OFF_NOTE)
            self._evict()
            self._runs[run_id] = run
            return run

    def require_access(self, access: Access) -> None:
        if access == Access.FULL and not self.full_access:
            raise RunError(FULL_ACCESS_NEEDS_FLAG)

    def delete(self, run_id: str) -> None:
        summary = db.get_thread(run_id)
        if summary is None:
            raise RunError("No such thread.")

        with self._lock:
            live = self._runs.pop(run_id, None)
            self._deleting.add(run_id)
        try:
            if live is not None:
                live.shut_down()
            events = db.load_events(run_id)
            db.delete_thread(run_id)
        finally:
            with self._lock:
                self._deleting.discard(run_id)

        folder = run_dir(run_id)
        providers.get(summary["provider"]).forget_thread(events, str(folder))
        if folder.exists():
            shutil.rmtree(folder)
        status_feed.publish({"kind": "list"})

    def close(self) -> None:
        with self._lock:
            live, self._runs = list(self._runs.values()), {}
        for run in live:
            run.shut_down()

    def _evict(self) -> None:
        now = db.now_ms()
        idle = sorted(
            (r for r in self._runs.values() if r.idle() and now - r.touched > EVICT_GRACE_MS),
            key=lambda r: r.touched,
        )
        for run in idle:
            if now - run.touched > IDLE_EVICT_MS or len(self._runs) > MAX_CACHED_RUNS:
                run.browser.close()
                del self._runs[run.id]


def _new_id() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=RUN_ID_SUFFIX_CHARS))
    return f"r{_base36(db.now_ms())}{suffix}"


def _copy_folder(source_id: str, child_id: str) -> None:
    source = run_dir(source_id)
    ignored = shutil.ignore_patterns(f"*{RECORD_SUFFIX}")
    shutil.copytree(source, run_dir(child_id), ignore=ignored, dirs_exist_ok=True)


def _base36(value: int) -> str:
    out = ""
    while value:
        value, rest = divmod(value, len(BASE36_DIGITS))
        out = BASE36_DIGITS[rest] + out
    return out or "0"


runs = RunManager()
