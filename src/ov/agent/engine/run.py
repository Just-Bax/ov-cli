from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from ov.agent import providers
from ov.agent.engine import cases, guard
from ov.agent.engine.browsing import BrowserSlot
from ov.agent.engine.cancel import Cancel
from ov.agent.engine.conversation import answered
from ov.agent.engine.export import stored_state, to_markdown
from ov.agent.engine.files import run_dir
from ov.agent.engine.prompt import system_prompt
from ov.agent.engine.run_branch import INHERITED_RETRY, BranchMixin, BranchPoint
from ov.agent.engine.run_browser import BrowserMixin
from ov.agent.engine.run_cases import CasesMixin
from ov.agent.engine.run_common import RunError, uid
from ov.agent.engine.run_compaction import CompactionMixin
from ov.agent.engine.run_events import EventsMixin
from ov.agent.engine.run_grids import GridsMixin
from ov.agent.engine.run_guard import GuardMixin
from ov.agent.engine.run_questions import QuestionsMixin
from ov.agent.engine.run_queue import QueueMixin
from ov.agent.engine.run_titles import TitlesMixin
from ov.agent.engine.run_tools import ToolsMixin
from ov.agent.engine.tasks import Task
from ov.agent.providers.base import AgentProvider, Initiator
from ov.agent.storage import db
from ov.agent.storage.models import Access

RESTART_NOTE = (
    "OV Agent restarted while you were working, so your turn stopped part way. Tool calls that were running were "
    "cut off and their results are unknown: check the current state before you redo anything that changes "
    "something, then carry on with the user's request."
)
START_TURN = "u_start"
SHUTDOWN_SECONDS = 10
SHUTDOWN_POLL_SECONDS = 0.05
STREAM_END = object()
SAME_THREAD = "That is this thread; its history is already in your context."
NO_THREAD = "No thread {id}. Ask the user for the id from the thread's menu: Copy thread ID."
STOPPABLE = ("queued", "running", "waiting")
TASK_FINISHED = "[Background task finished: {label}]\n{result}"

CHANGES_POSSIBLE = (
    "Changes through ov, ov_import, the PagerDuty change tools, the browser, workspace edits and commands that "
    "change something are now possible"
)
ACCESS_NOTES = {
    Access.READ: "The user switched this run to Read-only. Make no changes; propose them instead.",
    Access.ASK: (
        f"The user switched this run to Always ask. {CHANGES_POSSIBLE}; instance, PagerDuty and browser "
        "changes, pushes and other outside effects wait for their approval. Apply only what the agreed plan needs."
    ),
    Access.AUTO: (
        f"The user switched this run to Auto. {CHANGES_POSSIBLE} and run without asking the user; only risky ones "
        "such as deletes, force pushes or bulk changes wait for their approval. Apply only what the agreed plan needs."
    ),
    Access.FULL: (
        f"The user switched this run to Full access. {CHANGES_POSSIBLE} and run without any check or question, "
        "deletes and pushes included. Be careful: apply only what the agreed plan needs."
    ),
}


class Run(
    EventsMixin,
    QuestionsMixin,
    QueueMixin,
    ToolsMixin,
    GuardMixin,
    BrowserMixin,
    CasesMixin,
    TitlesMixin,
    CompactionMixin,
    GridsMixin,
    BranchMixin,
):
    turns: dict[str, int]
    _saved: list[str]
    _tasks: dict[str, Task]
    _finished_tasks: list[Task]
    _verdicts: dict[tuple[str, ...], guard.Verdict]
    _fork: dict[str, Any] | None
    _compacting: dict[str, Any] | None
    _stable: BranchPoint | None
    _vague_title: str | None

    def __init__(self, run_id: str, state: dict[str, Any], seq: int) -> None:
        self.id, self.state, self.seq = run_id, state, seq
        self.work_dir = run_dir(run_id)
        self.cancel = Cancel()
        self.opened: set[str] = set()
        self.vision = True
        self._lock = threading.RLock()
        self._listeners: list[queue.Queue[dict[str, Any]]] = []
        self._loaded_messages: list[dict[str, Any]] | None = None
        self.turns, self._saved = {}, []
        self._cut_off: set[str] = set()
        self._local = threading.local()
        self._pending_images: list[tuple[str, str]] = []
        self._notes: list[str] = []
        self._waits, self._background = 0, 0
        self._queue: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        self._steers: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        self._questions: dict[str, tuple[threading.Event, list[tuple[list[str], str]]]] = {}
        self._logins: dict[str, tuple[threading.Event, list[bool]]] = {}
        self._busy, self.finished = False, False
        self._vague_title, self._first_turn_over = None, False
        self._streaming: str | None = None
        self._tasks, self._finished_tasks, self._verdicts, self._fork, self._stable = {}, [], {}, None, None
        self._compacting, self.context_tokens = None, int((state.get("context") or {}).get("tokens") or 0)
        self.browser, self.touched = BrowserSlot(run_id, self.emit), db.now_ms()
        self._restore_queue()

    @property
    def messages(self) -> list[dict[str, Any]]:
        if self._loaded_messages is None:
            messages, self.turns = db.load_messages(self.id)
            self._saved = [json.dumps(m) for m in messages]
            self._loaded_messages = answered(messages)
        return self._loaded_messages

    @messages.setter
    def messages(self, messages: list[dict[str, Any]]) -> None:
        self._loaded_messages = messages

    def persist(self) -> None:
        current = [json.dumps(m) for m in self.messages]
        start = next(
            (i for i, (old, new) in enumerate(zip(self._saved, current, strict=False)) if old != new),
            min(len(self._saved), len(current)),
        )
        if start == len(current) == len(self._saved):
            return

        turns = {index: turn_id for turn_id, index in self.turns.items()}
        db.save_messages(self.id, start, self.messages[start:], turns)
        self._saved = current

    @property
    def instance(self) -> str:
        return self.state["summary"].get("instance") or ""

    @property
    def provider(self) -> str:
        return str(self.state["summary"]["provider"])

    @property
    def agent(self) -> AgentProvider:
        return providers.get(self.provider)

    @property
    def model(self) -> str:
        return str(self.state["summary"]["model"])

    @property
    def access(self) -> Access:
        return Access(self.state["access"])

    def _helper_model(self) -> str:
        return self.agent.helper_model(db.provider_models(self.provider)[1])

    def working(self) -> bool:
        with self._lock:
            return self._busy or bool(self._background)

    def idle(self) -> bool:
        with self._lock:
            return not (
                self._busy
                or self._listeners
                or self._questions
                or self._logins
                or self._queue
                or self._streaming
                or self._background
            )

    def shut_down(self) -> None:
        self.stop()
        self.browser.close()
        deadline = time.monotonic() + SHUTDOWN_SECONDS
        while self.working():
            if time.monotonic() > deadline:
                raise RunError("The thread is still stopping. Try again in a moment.")
            time.sleep(SHUTDOWN_POLL_SECONDS)

        with self._lock:
            listeners, self._listeners = self._listeners, []
        for channel in listeners:
            channel.put(STREAM_END)

    def _claim(self) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self.cancel = Cancel()
            return True

    def _spawn(self, target: Callable[..., None], *args: Any) -> None:
        with self._lock:
            self._background += 1

        def work() -> None:
            try:
                target(*args)
            finally:
                with self._lock:
                    self._background -= 1

        threading.Thread(target=work, daemon=True, name=f"run-{self.id}").start()

    def set_access(self, access: Access, note: str | None = None) -> None:
        if self.access == access:
            return
        self.emit({"type": "access", "access": access})
        self._notes.append(note or ACCESS_NOTES[access])

    def stop(self) -> None:
        self.cancel.set()
        with self._lock:
            questions, self._questions = self._questions, {}
            logins, self._logins = self._logins, {}
            self._finished_tasks = []
            self._queue_held = bool(self._queue)

        self._stop_tasks()
        if self._queue_held:
            self._emit_queue()

        for question_id, (event, answer) in questions.items():
            self._close_question(question_id)
            answer.append(([], ""))
            event.set()

        for event, ok in logins.values():
            ok.append(False)
            event.set()

        if self.state["summary"]["status"] in STOPPABLE:
            self._set_status("cancelled")

    def finish(self, outcome: dict[str, Any]) -> None:
        self.finished = True
        self.emit({"type": "outcome", "outcome": outcome})

    def read_thread(self, thread_id: str) -> str:
        if thread_id == self.id:
            raise RunError(SAME_THREAD)
        stored = stored_state(thread_id)
        if stored is None:
            raise RunError(NO_THREAD.format(id=thread_id))
        return to_markdown(stored[0])

    def begin(self, data: dict[str, Any]) -> None:
        self._busy = True
        self._spawn(self._start, data)

    def _start(self, data: dict[str, Any]) -> None:
        try:
            self._set_status("running")
            uploaded = self._copy_uploads(data.get("attachments") or [])
            text = (data.get("prompt") or "").strip()
            self.emit({"type": "user_message", "message": self._message(START_TURN, text, uploaded)})
            self.vision = self.agent.supports_vision(self.model)

            ref = None if uploaded else cases.case_ref(text)
            if not ref and text:
                self._name_later(text)
            content = self._preload_case(ref) if ref else self._user_content(text, uploaded)
            self.messages = [{"role": "system", "content": system_prompt(self.access, self.instance)}]
            self._push_turn(START_TURN, content)
            self._loop(Initiator.USER)
        except Exception as exc:
            self._fail(exc)
        finally:
            self._busy = False
            self._mark_stable()
            self._first_turn_ended()
            self._pick_up_queue()

    def retry(self, item_id: str) -> None:
        if self.inherited_item(item_id):
            raise RunError(INHERITED_RETRY)

        index = self.turns.get(item_id) if self.messages else None
        message = next((m for m in self.state["chat"] if m["id"] == item_id and m["role"] == "user"), None)
        if index is None or message is None:
            raise RunError("This message cannot be retried.")

        anchor = self.agent.retry_anchor(self, item_id)
        if not self._claim():
            raise RunError("Wait for the agent to finish, or stop it, before retrying.")

        self._stop_tasks()
        with self._lock:
            self._finished_tasks = []
        self._take_steers()
        self._fork = anchor

        content = self.messages[index]["content"]
        self.messages = self.messages[:index]
        self.turns = {k: i for k, i in self.turns.items() if i < index}
        self.emit({"type": "rewind", "itemId": item_id})
        self.emit({"type": "user_message", "message": {**message, "ts": db.now_ms()}})
        self._push_turn(item_id, content)
        self._spawn(self._run_turn)

    def resume_after_restart(self) -> None:
        if not self.messages or not self._claim():
            return
        self.add_note(RESTART_NOTE)
        self._spawn(self._run_turn, None, Initiator.AGENT)

    def _run_turn(self, woken_by: str | None = None, initiator: Initiator = Initiator.USER) -> None:
        try:
            self._set_status("running", woken_by=woken_by)
            self._deliver_queued(starting_turn=True)
            self._loop(Initiator.AGENT if woken_by else initiator)
        except Exception as exc:
            self._fail(exc)
        finally:
            self._busy = False
            self._mark_stable()
            self._pick_up_queue()

    def _fail(self, exc: Exception) -> None:
        self.compaction_failed(str(exc) or type(exc).__name__)

        with self._lock:
            live = set(self._tasks)

        for tool in [t for t in self.state["tools"] if t["status"] == "running" and t["id"] not in live]:
            self.emit({"type": "tool", "tool": {"id": tool["id"], "status": "error", "output": "Interrupted."}})

        if self.cancel.is_set():
            self._set_status("cancelled")
            return
        self._set_status("error", str(exc) or type(exc).__name__)

    def _loop(self, initiator: Initiator) -> None:
        self.cancel.check()
        self.agent.run_turn(self, initiator)
        self.cancel.check()
        self._set_status("running" if self._background_live() else "done")

    def add_note(self, note: str) -> None:
        with self._lock:
            self._notes.append(note)

    def take_input(self) -> None:
        with self._lock:
            notes, self._notes = self._notes, []
        if notes:
            self.messages.append({"role": "user", "content": f"[{' '.join(notes)}]"})

        with self._lock:
            finished, self._finished_tasks = self._finished_tasks, []
        for task in finished:
            result = TASK_FINISHED.format(label=task.label, result=task.result)
            self.messages.append({"role": "user", "content": result})

        if self._steering():
            self._deliver_queued()
            self.finished = False

    def session_input(self) -> tuple[str | None, list[Any]]:
        self.take_input()

        last_reply = max((i for i, m in enumerate(self.messages) if m["role"] == "assistant"), default=-1)
        pending = range(last_reply + 1, len(self.messages))
        turn = next((t for t, i in self.turns.items() if i in pending), None)

        contents = [self.messages[i]["content"] for i in pending if self.messages[i]["role"] == "user"]
        if contents:
            self.messages.append({"role": "assistant", "content": None})
            self.persist()

        return turn, contents

    def take_fork(self) -> dict[str, Any] | None:
        fork, self._fork = self._fork, None
        return fork

    def new_message_id(self) -> str:
        return uid("a")

    def mark_cut_off(self, call_ids: set[str]) -> None:
        self._cut_off.update(call_ids)
