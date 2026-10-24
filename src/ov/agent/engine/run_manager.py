from __future__ import annotations

import random
import shutil
import string
import threading
from typing import Any

from ov.agent import providers
from ov.agent.engine.feed import status_feed
from ov.agent.engine.files import run_dir
from ov.agent.engine.run import Run
from ov.agent.engine.run_common import RunError
from ov.agent.engine.run_titles import TITLE_CHARS, short_title
from ov.agent.engine.state import empty_state, reduce
from ov.agent.storage import db
from ov.agent.storage.models import Access

CONTINUE_WHILE_BUSY = "Wait for the agent to finish, or stop it, before continuing in a new thread."
NOTHING_TO_CONTINUE = "This thread has nothing to carry over yet."
CONTINUED_TITLE = "{title} (continued)"
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
        run = self._new(
            title, provider=provider, model=model, prompt=prompt, instance=data.get("instance"), access=access
        )
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

        source_title = source.state["summary"]["title"]
        title = short_title(CONTINUED_TITLE.format(title=source_title), TITLE_CHARS)
        run = self._new(
            title,
            provider=source.provider,
            model=source.model,
            prompt="",
            instance=source.instance or None,
            access=source.access,
        )
        run.emit({"type": "meta", "continuedFrom": {"id": source.id, "title": source_title}})
        source.emit({"type": "meta", "continuedIn": {"id": run.id, "title": title}})
        run.carry_over(source_title, history)
        return run

    def _new(self, title: str, *, provider: str, model: str, prompt: str, instance: str | None, access: Access) -> Run:
        providers.get(provider)
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=RUN_ID_SUFFIX_CHARS))
        run_id = f"r{_base36(db.now_ms())}{suffix}"
        summary = db.create_thread(run_id, title, provider, model, prompt=prompt, instance=instance, access=access)

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

            summary = db.get_thread(run_id)
            if summary is None:
                return None

            state = empty_state(summary, db.thread_access(run_id))
            events = db.load_events(run_id)
            for event in events:
                reduce(state, event)
            state["summary"] = {**state["summary"], **summary}
            state.pop("browser", None)
            run = Run(run_id, state, events[-1]["seq"] if events else -1)
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


def _base36(value: int) -> str:
    out = ""
    while value:
        value, rest = divmod(value, len(BASE36_DIGITS))
        out = BASE36_DIGITS[rest] + out
    return out or "0"


runs = RunManager()
