from __future__ import annotations

import base64
import difflib
import itertools
import json
import queue
import random
import re
import shutil
import string
import threading
import time
from collections.abc import Callable
from typing import Any

from ov.agent import providers
from ov.agent import workspace as project
from ov.agent.engine import cases, compaction, guard
from ov.agent.engine.browsing import BrowserSlot
from ov.agent.engine.cancel import Cancel
from ov.agent.engine.conversation import answered
from ov.agent.engine.files import (
    IMAGE_EXTS,
    attachments_dir,
    describe,
    image_mime,
    run_dir,
    unique_path,
    uploads_dir,
    within,
)
from ov.agent.engine.links import links_for, seen_ids
from ov.agent.engine.prompt import stamped, system_prompt
from ov.agent.engine.state import details, empty_state, question_text, reduce, search, snapshot, window
from ov.agent.engine.tasks import Task, TaskContext
from ov.agent.instances.ovproc import find_instance, url_for, web_cookies
from ov.agent.instances.ovproc import login as ov_login
from ov.agent.integrations.common import Usage
from ov.agent.providers.base import AgentProvider, Initiator
from ov.agent.storage import db
from ov.agent.storage.models import Access, UsageKind
from ov.agent.tools import tool_named
from ov.agent.tools.base import APPROVE, REJECT, Approval, Tool, ToolError, clip

NOTHING_TO_COMPACT = "There is nothing to compact in this thread yet."
COMPACT_WHILE_BUSY = "Wait for the agent to finish, or stop it, before compacting."
CONTINUE_WHILE_BUSY = "Wait for the agent to finish, or stop it, before continuing in a new thread."
NOTHING_TO_CONTINUE = "This thread has nothing to carry over yet."
CONTINUED_TITLE = "{title} (continued)"
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
RESTART_NOTE = (
    "OV Agent restarted while you were working, so your turn stopped part way. Tool calls that were running were "
    "cut off and their results are unknown: check the current state before you redo anything that changes "
    "something, then carry on with the user's request."
)
MAX_BACKGROUND_TASKS = 8
TOOL_INPUT_CHARS = 8000
TOOL_OUTPUT_CHARS = 12000
TOOL_ERROR_CHARS = 4000
BAD_ARGS_CHARS = 200
LOGIN_MESSAGE_CHARS = 300
TITLE_CHARS = 72
PROMPT_TITLE_CHARS = 60
NAMING_INPUT_CHARS = 2000
NAMING_MAX_TOKENS = 200
NAMING_PROMPT = (
    "You write titles for a list of conversations. You never answer or act on the request. "
    "Given the user's first message between <message> tags, reply with a 3 to 7 word title "
    "naming its topic, like a ticket title. Reply with the title only: one line, no quotes, no "
    "markdown, no trailing period."
)
MAX_TITLE_WORDS = 8
RETITLE_CHARS = 1500
_TITLE_PREFIX = re.compile(r"^(title|subject|topic)\s*[:\-]\s*", re.IGNORECASE)
_TITLE_NOISE = "\"'#*`_.:;,- "
RUN_ID_SUFFIX_CHARS = 4
BASE36_DIGITS = string.digits + string.ascii_lowercase
IDLE_EVICT_MS = 5 * 60_000
MAX_CACHED_RUNS = 6
LOGIN_ATTEMPTS = 2
EVICT_GRACE_MS = 60_000
START_TURN = "u_start"
SHUTDOWN_SECONDS = 10
STREAM_END = object()
WAKE_STATUSES = ("waiting", "error", "done")
SHUTDOWN_POLL_SECONDS = 0.05

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
FULL_ACCESS_NEEDS_FLAG = "Full access needs OV Agent started with: ov agent --full-access"
FULL_ACCESS_OFF_NOTE = (
    "Full access is off because OV Agent was started without --full-access. This run is now on Auto: only risky "
    "changes wait for the user's approval."
)
BROWSER_OPENED_NOTE = (
    "The user opened {alias} in the browser beside the chat. You both see it and the user may click in it too. "
    "Questions about what is on screen and requests to go somewhere or do something there are about this browser: "
    "hand them to browser_run as goals; ov only reads while it is open."
)
BROWSER_CLOSED_NOTE = "The user closed the browser."
BACKGROUND_STARTED = (
    "Running in the background as {label}. Its result arrives as a message when it finishes. Continue with "
    "checks that do not depend on it, or end your turn and you will be woken with the result. Do not guess "
    "its result."
)
BACKGROUND_FULL = "{count} tasks already run in the background. Wait for one to finish first."
TASK_FINISHED = "[Background task finished: {label}]\n{result}"
TASK_STOPPED_NOTE = "The user stopped the background task {label}; it gave no result."
STOPPED_BY_USER = "Stopped by the user."
STEERED = "[The user wrote while you worked: {text}]"

CLOSED_LOGINS = ("done", "failed", "skipped")
APPROVAL_ANSWERS = ([APPROVE], [REJECT])
EDIT_CHARS = 60_000
CUT_OFF_ARGUMENTS = (
    "the arguments of this call were cut off or were not valid JSON, so it did not run. This "
    "usually means the content was too long for one reply. Do not resend it in one piece: write a "
    "large file in parts (ws_write a short first part, then add the rest with ws_edit), or shorten it."
)

_ids = itertools.count(1)


class RunError(Exception):
    pass


def _uid(prefix: str) -> str:
    return f"{prefix}_{db.now_ms()}_{next(_ids)}"


class StatusFeed:
    def __init__(self) -> None:
        self._listeners: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> tuple[queue.Queue[dict[str, Any]], Callable[[], None]]:
        channel: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._listeners.append(channel)

        def unsubscribe() -> None:
            with self._lock:
                if channel in self._listeners:
                    self._listeners.remove(channel)

        return channel, unsubscribe

    def publish(self, change: dict[str, Any]) -> None:
        with self._lock:
            for channel in self._listeners:
                channel.put(change)


status_feed = StatusFeed()


class Run:
    turns: dict[str, int]
    _saved: list[str]
    _tasks: dict[str, Task]
    _finished_tasks: list[Task]
    _verdicts: dict[tuple[str, ...], guard.Verdict]
    _fork: dict[str, Any] | None
    _compacting: dict[str, Any] | None

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
        self._held: set[str] = set()
        self._questions: dict[str, tuple[threading.Event, list[tuple[list[str], str]]]] = {}
        self._logins: dict[str, tuple[threading.Event, list[bool]]] = {}
        self._busy, self.finished = False, False
        self._streaming: str | None = None
        self._tasks, self._finished_tasks, self._verdicts, self._fork = {}, [], {}, None
        self._compacting, self.context_tokens = None, int((state.get("context") or {}).get("tokens") or 0)
        self.browser, self.touched = BrowserSlot(run_id, self.emit), db.now_ms()
        self._restore_queue()

    def _restore_queue(self) -> None:
        for message in self.state["queued"]:
            files = message.get("files") or []
            uploaded = [describe(attachments_dir(self.id) / f["name"], "upload") for f in files]
            self._queue.append((message, uploaded))
            self._held.add(message["id"])

        self._queue_held = bool(self._queue)
        self.state["queued"] = [{**m, "steer": False} for m in self.state["queued"]]
        self.state["queueHeld"] = self._queue_held

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

    def snapshot(self, turns: int) -> str:
        with self._lock:
            return json.dumps({**snapshot(self.state, turns), "seq": self.seq})

    def history(self, end: int, turns: int) -> str:
        with self._lock:
            return json.dumps(window(self.state, min(end, len(self.state["items"])), turns))

    def search(self, query: str) -> dict[str, list[int]]:
        with self._lock:
            return {"items": search(self.state, query)}

    def details(self, tool_ids: set[str], edit_ids: set[str]) -> str:
        with self._lock:
            return json.dumps(details(self.state, tool_ids, edit_ids))

    def resume(self, after: int) -> tuple[queue.Queue[dict[str, Any]], Callable[[], None], list[dict[str, Any]]]:
        channel: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._listeners.append(channel)
            backlog = db.load_events(self.id, after)
            partial = next((m for m in self.state["chat"] if m["id"] == self._streaming), None)
            if partial is not None:
                event = {"type": "message", "messageId": partial["id"], "text": partial["text"], "ts": partial["ts"]}
                backlog.append({"seq": self.seq, "ts": db.now_ms(), "live": True, "event": event})

        def unsubscribe() -> None:
            with self._lock:
                if channel in self._listeners:
                    self._listeners.remove(channel)
                self.touched = db.now_ms()

        return channel, unsubscribe, backlog

    def stream_text(self, message_id: str, delta: str) -> None:
        with self._lock:
            self._streaming = message_id

            live = {
                "seq": self.seq,
                "ts": db.now_ms(),
                "live": True,
                "event": {"type": "text", "messageId": message_id, "delta": delta},
            }
            reduce(self.state, live)

            for channel in self._listeners:
                channel.put(live)

    def commit_text(self, message_id: str) -> None:
        with self._lock:
            self._streaming = None
            message = next((m for m in self.state["chat"] if m["id"] == message_id), None)
        if message is None:
            return

        event: dict[str, Any] = {
            "type": "message",
            "messageId": message_id,
            "text": message["text"],
            "ts": message["ts"],
        }

        found = find_instance(self.instance) if self.instance else None
        if found is not None:
            with self._lock:
                linked = links_for(message["text"], found["url"], seen_ids(self.state))
            if linked["mentions"] or linked["unverified"]:
                event["links"] = linked

        self.emit(event)

    def record_usage(self, model: str, kind: str, usage: Usage | None) -> None:
        if usage is None:
            return
        cost = db.add_usage(self.id, self.provider, model, kind, tokens=usage.tokens, nano=usage.nano)

        with self._lock:
            self.state["summary"]["cost"] = cost
            live = {"seq": self.seq, "ts": db.now_ms(), "live": True, "event": {"type": "cost", "cost": cost}}
            for channel in self._listeners:
                channel.put(live)

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.touched = db.now_ms()
            self.seq += 1

            stored = db.append_event(self.id, self.seq, event)
            reduce(self.state, stored)

            kind = event["type"]
            if kind == "status":
                db.update_thread(self.id, status=event["status"])
                self._raise_hand(event["status"])
            elif kind == "meta":
                db.update_thread(self.id, title=event.get("title"), instance=event.get("instance"))
                status_feed.publish({"kind": "meta", "id": self.id})
            elif kind == "access":
                db.update_thread(self.id, access=event["access"])

            for channel in self._listeners:
                channel.put(stored)

    def _raise_hand(self, status: str) -> None:
        if status in WAKE_STATUSES:
            db.set_snoozed(self.id, None)
        if status == "waiting":
            db.set_settled(self.id, False)

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

    def _set_status(self, status: str, error: str | None = None, woken_by: str | None = None) -> None:
        with self._lock:
            if self.state["summary"]["status"] == status and not error and not woken_by:
                return
            event: dict[str, Any] = {"type": "status", "status": status}
            if error:
                event["error"] = error
            if woken_by:
                event["wokenBy"] = woken_by
            self.emit(event)

        status_feed.publish(
            {"kind": "status", "id": self.id, "status": status, "title": self.state["summary"]["title"]}
        )

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

    def open_browser(self, ref: str) -> None:
        wanted = ref or self.instance
        if not wanted:
            raise RunError("This thread has no instance yet.")

        found = find_instance(wanted)
        if found is None:
            raise RunError(f"{wanted} is not a signed-in instance.")

        pilot = self.browser.start(found["alias"], found["url"], web_cookies(found["alias"]))
        self._notes.append(BROWSER_OPENED_NOTE.format(alias=found["alias"]))
        self.browser.navigate(pilot.url_of(""))

    def close_browser(self) -> None:
        if self.browser.live:
            self._notes.append(BROWSER_CLOSED_NOTE)
        self.browser.close()

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
            self._held = {q[0]["id"] for q in self._queue}
            self._queue_held = bool(self._queue)
            idle = not self._busy
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
        if idle and self.state["summary"]["status"] == "running":
            self._set_status("cancelled")

    def _stop_tasks(self) -> None:
        with self._lock:
            live = list(self._tasks.values())
        for task in live:
            self._stop_task(task)

    def _stop_task(self, task: Task) -> None:
        with self._lock:
            if task.finished or task.stopped_at is not None:
                return
            task.stopped_at = db.now_ms()
        task.cancel.set()
        self.emit({"type": "tool", "tool": {"id": task.id, "stoppedAt": task.stopped_at}})

    def stop_tool(self, tool_id: str) -> None:
        with self._lock:
            task = self._tasks.get(tool_id)
        if task is None:
            raise RunError("That tool is no longer running.")

        self._stop_task(task)
        if task.backgrounded_at is not None:
            self._notes.append(TASK_STOPPED_NOTE.format(label=task.label))

    def move_to_background(self, tool_id: str) -> None:
        with self._lock:
            task = self._tasks.get(tool_id)
            if task is None or task.finished:
                raise RunError("That tool is no longer running.")
            if task.backgrounded_at is not None:
                return
            if self._questions or self._logins:
                raise RunError("Answer the open question first.")
            self._check_background_room()
            task.backgrounded_at = db.now_ms()
        self.emit({"type": "tool", "tool": {"id": task.id, "backgroundedAt": task.backgrounded_at}})
        task.settled.set()

    def _check_background_room(self) -> None:
        count = len(self._background_tasks())
        if count >= MAX_BACKGROUND_TASKS:
            raise RunError(BACKGROUND_FULL.format(count=count))

    def answer(self, question_id: str, answers: list[str], note: str = "") -> None:
        question = next((q for q in self.state["questions"] if q["id"] == question_id), None)
        if question is None:
            raise RunError("No such question in this run.")

        _check_answers(question, answers)

        with self._lock:
            waiter = self._questions.pop(question_id, None)
        if waiter is None:
            self._close_question(question_id)
            raise RunError("The agent is no longer waiting for this answer. Send a message to continue.")

        closed = {**question, "answers": answers}
        if note.strip():
            closed["note"] = note.strip()
        self.emit({"type": "question", "question": closed})
        waiter[1].append((answers, closed.get("note", "")))
        waiter[0].set()

    def _close_question(self, question_id: str) -> None:
        question = next((q for q in self.state["questions"] if q["id"] == question_id), None)
        if question is not None and "answers" not in question and not question.get("stopped"):
            self.emit({"type": "question", "question": {**question, "stopped": True}})

    def ask_user(self, items: list[dict[str, Any]]) -> list[str]:
        answers, _ = self._ask({"kind": "ask", "items": items})
        return answers

    def ask_approval(self, question: str, detail: str, reason: str = "") -> Approval:
        entry: dict[str, Any] = {"kind": "approval", "question": question, "detail": detail}
        if reason:
            entry["reason"] = reason
        answers, note = self._ask(entry)
        return Approval(answers == [APPROVE], note)

    def _ask(self, entry: dict[str, Any]) -> tuple[list[str], str]:
        entry = {"id": _uid("q"), **entry}
        tool_id = getattr(self._local, "tool", "")
        if tool_id:
            entry["toolId"] = tool_id

        event, holder = threading.Event(), []
        with self._lock:
            self._questions[entry["id"]] = (event, holder)
            self.cancel.check()

        self.emit({"type": "question", "question": entry})
        self._wait_for(event)
        return holder[0]

    def _wait_for(self, event: threading.Event) -> None:
        with self._lock:
            self._waits += 1
            first = self._waits == 1
        if first:
            self._set_status("waiting")

        try:
            event.wait()
        finally:
            with self._lock:
                self._waits -= 1
                last = self._waits == 0

        self.cancel.check()
        if last:
            self._set_status("running")

    def require_login(self, host: str, tenant: str = "") -> bool:
        with self._lock:
            existing = next(
                (
                    item
                    for item in self.state["logins"]
                    if item["instance"] == host
                    and (item.get("tenant") or "") == tenant
                    and item["state"] not in CLOSED_LOGINS
                ),
                None,
            )

            login_id = existing["id"] if existing else _uid("login")
            waiter = self._logins.setdefault(login_id, (threading.Event(), []))
            if existing is None:
                prompt = {
                    "id": login_id,
                    "instance": host,
                    "url": url_for(host),
                    "state": "needed",
                    **({"tenant": tenant} if tenant else {}),
                }
                self.emit({"type": "login", "login": prompt})

            self.cancel.check()

        self._wait_for(waiter[0])
        return waiter[1][0]

    def login(
        self,
        login_id: str,
        skip: bool,
        token: str = "",
        screen: tuple[int, int] | None = None,
        remember: bool = False,
    ) -> dict[str, Any]:
        prompt = next((item for item in self.state["logins"] if item["id"] == login_id), None)
        if prompt is None:
            raise RunError("No such login prompt.")
        if skip:
            self.emit({"type": "login", "login": {**prompt, "state": "skipped"}})
            self._resolve_login(login_id, False)
            return {"ok": False, "message": "Skipped"}

        self.emit({"type": "login", "login": {**prompt, "state": "running"}})

        result = ov_login(prompt["url"], prompt.get("tenant") or "", token, screen, remember)
        ok = result.code == 0
        message = "" if ok else result.message[-LOGIN_MESSAGE_CHARS:] or "Sign-in failed."
        update = {**prompt, "state": "done" if ok else "failed"}
        if not ok:
            update["message"] = message

        self.emit({"type": "login", "login": update})
        if ok:
            self._resolve_login(login_id, True)
        return {"ok": ok, "message": message}

    def _resolve_login(self, login_id: str, ok: bool) -> None:
        with self._lock:
            waiter = self._logins.pop(login_id, None)
        if waiter is not None:
            waiter[1].append(ok)
            waiter[0].set()

    def record_edit(self, path: str, before: str, after: str, created: bool) -> None:
        added, removed = _line_changes(before, after)
        truncated = len(before) > EDIT_CHARS or len(after) > EDIT_CHARS
        edit = {
            "id": _uid("e"),
            "toolId": getattr(self._local, "tool", ""),
            "path": path.replace("\\", "/"),
            "created": created,
            "added": added,
            "removed": removed,
            "before": before[:EDIT_CHARS],
            "after": after[:EDIT_CHARS],
            "truncated": truncated,
        }

        self.emit({"type": "edit", "edit": edit})

    def attach_image(self, name: str, url: str) -> None:
        self._pending_images.append((name, url))

    def has_outcome(self) -> bool:
        return bool(self.state.get("outcome"))

    @property
    def access(self) -> Access:
        return Access(self.state["access"])

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

    def drive_browser(self, goal: str, cancel: Cancel) -> str:
        return self.agent.drive_browser(self, self._helper_model(), goal, cancel)

    def record_step_usage(self, model: str, usage: Usage | None) -> None:
        self.record_usage(model, UsageKind.STEP, usage)

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

    def finish(self, outcome: dict[str, Any]) -> None:
        self.finished = True
        self.emit({"type": "outcome", "outcome": outcome})

    def begin(self, data: dict[str, Any]) -> None:
        self._busy = True
        self._spawn(self._start, data)

    def _start(self, data: dict[str, Any]) -> None:
        try:
            self._set_status("running")
            uploaded = self._copy_uploads(data.get("attachments") or [], START_TURN)
            text = (data.get("prompt") or "").strip()
            self.emit({"type": "user", "message": self._message(START_TURN, text, uploaded)})
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
            self._pick_up_queue()

    def _preload_case(self, ref: str) -> str:
        tool = {"id": _uid("load"), "name": "ov_case", "label": f"Read case {ref} from trackor"}
        started = db.now_ms()
        self.emit({"type": "tool", "tool": {**tool, "status": "running"}})
        try:
            text = self.load_case(ref)
        except Exception as exc:
            self._tool_done(tool, "error", started, str(exc)[:TOOL_ERROR_CHARS])
            raise
        self._tool_done(tool, "ok", started, text[:TOOL_OUTPUT_CHARS])
        return f"Troubleshoot this case.\n\n{clip(text, self, 'case')}"

    def load_case(self, ref: str) -> str:
        return self.read_case(ref, self.cancel, names_thread=True)

    def read_case(self, ref: str, cancel: Cancel, names_thread: bool = False) -> str:
        for attempt in range(LOGIN_ATTEMPTS):
            try:
                bundle = cases.load_case(ref, self.work_dir, cancel)
                break
            except cases.NeedsLogin as exc:
                if attempt or not self.require_login(exc.host):
                    raise RunError(f"Not signed in to {exc.host}.") from None

        text = cases.render(bundle, self.work_dir)
        if self.state["summary"].get("caseKey"):
            return text

        meta = {"type": "meta", "caseKey": bundle["key"], "caseUrl": bundle["url"], "instance": bundle["website"]}
        if names_thread:
            title = " ".join(bundle["title"].split()) or f"Case {bundle['key']}"
            meta["title"] = short_title(f"{bundle['key']}: {title}", TITLE_CHARS)
        self.emit(meta)
        if bundle["website"]:
            text += f"\n\nThe run's default instance is now {bundle['website']}."
        return text

    def follow_up(self, text: str, files: list[dict[str, str]], steer: bool) -> None:
        claimed = self._claim()
        if claimed and not self.messages:
            self._busy = False
            raise RunError("This run has no conversation to continue.")

        try:
            message_id = _uid("u")
            uploaded = self._copy_uploads(files, message_id)
            message = self._message(message_id, text, uploaded)
            content = self._user_content(text, uploaded) if claimed else None
        except Exception:
            if claimed:
                self._busy = False
            raise

        if not claimed:
            with self._lock:
                self._queue.append((message, uploaded))
                if not steer:
                    self._held.add(message["id"])
            self.emit({"type": "queued", "message": {**message, "steer": steer}})
            self._pick_up_queue()
            return

        self.emit({"type": "user", "message": message})
        self._push_turn(message["id"], content)
        self._spawn(self._run_turn)

    def _startable(self) -> bool:
        return bool(self._queue) and not self._queue_held

    def _pick_up_queue(self) -> None:
        with self._lock:
            waiting = self._startable() or bool(self._finished_tasks)
            woken_by = self._finished_tasks[0].id if self._finished_tasks and not self._startable() else None
        if waiting and self._claim():
            self._spawn(self._run_turn, woken_by)

    def _helper_model(self) -> str:
        preferences = db.get_preferences()
        chosen = preferences["fastModel"] if preferences["provider"] == self.provider else ""
        return self.agent.helper_model(chosen)

    def _name_later(self, text: str) -> None:
        self._spawn(self._name, self.state["summary"]["title"], text)

    def _name(self, placeholder: str, text: str) -> None:
        title = self._ask_title(f"<message>\n{text[:NAMING_INPUT_CHARS]}\n</message>")
        if self.state["summary"]["title"] == placeholder:
            self.rename(title)

    def _ask_title(self, body: str) -> str:
        model = self._helper_model()
        reply, usage = self.agent.complete(model, NAMING_PROMPT, body, NAMING_MAX_TOKENS)
        self.record_usage(model, UsageKind.NAMING, usage)
        title = clean_title(reply)
        if not title:
            raise RunError(f"{model} did not suggest a title.")
        return title

    def retitle(self) -> str:
        with self._lock:
            chat = list(self.state["chat"])

        asked = next((m["text"] for m in chat if m["role"] == "user"), "")
        replied = next((m["text"] for m in reversed(chat) if m["role"] == "assistant" and m["text"].strip()), "")
        body = f"<message>\n{asked[:NAMING_INPUT_CHARS]}\n</message>\n\n<answer>\n{replied[:RETITLE_CHARS]}\n</answer>"
        title = self._ask_title(body)
        self.rename(title)
        return title

    def rename(self, title: str) -> None:
        cleaned = short_title(title, TITLE_CHARS)
        if not cleaned:
            raise RunError("A run needs a name.")
        self.emit({"type": "meta", "title": cleaned})

    def remove_queued(self, message_id: str) -> None:
        with self._lock:
            self._queue = [q for q in self._queue if q[0]["id"] != message_id]
            self._held.discard(message_id)
        self.emit({"type": "unqueue", "id": message_id})
        self._settle_queue()

    def steer_queued(self, message_id: str) -> None:
        with self._lock:
            if not self._busy:
                raise RunError("There is no running turn to steer.")
            self._queued(message_id)
            self._held.discard(message_id)
        self._emit_queue()

    def edit_queued(self, message_id: str, text: str) -> None:
        with self._lock:
            message, uploaded = self._queued(message_id)
            if not text.strip() and not uploaded:
                raise RunError("A queued message needs text or files.")

            edited = {**message, "text": text}
            self._queue = [(edited, uploaded) if q[0]["id"] == message_id else q for q in self._queue]
            steer = message_id not in self._held
        self.emit({"type": "queued", "message": {**edited, "steer": steer}})

    def move_queued(self, message_id: str, before_id: str | None) -> None:
        with self._lock:
            entry = self._queued(message_id)
            rest = [q for q in self._queue if q is not entry]
            ids = [q[0]["id"] for q in rest]
            if before_id is not None and before_id not in ids:
                raise RunError("That message is no longer queued.")

            rest.insert(len(rest) if before_id is None else ids.index(before_id), entry)
            self._queue = rest
        self._emit_queue()

    def resume_queue(self) -> None:
        with self._lock:
            if not self._queue:
                raise RunError("Nothing is queued.")
            self._queue_held = False
        self._emit_queue()
        self._pick_up_queue()

    def _settle_queue(self) -> None:
        with self._lock:
            if self._queue or not self._queue_held:
                return
            self._queue_held = False
        self._emit_queue()

    def _emit_queue(self) -> None:
        with self._lock:
            order = [q[0]["id"] for q in self._queue]
            steering = [i for i in order if i not in self._held]
            held = self._queue_held
        self.emit({"type": "queue", "order": order, "steering": steering, "held": held})

    def _queued(self, message_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        entry = next((q for q in self._queue if q[0]["id"] == message_id), None)
        if entry is None:
            raise RunError("That message is no longer queued.")
        return entry

    def _steering(self) -> bool:
        with self._lock:
            return any(q[0]["id"] not in self._held for q in self._queue)

    def has_news(self) -> bool:
        with self._lock:
            return self._steering() or bool(self._finished_tasks)

    def retry(self, item_id: str) -> None:
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

        self._fork = anchor

        content = self.messages[index]["content"]
        self.messages = self.messages[:index]
        self.turns = {k: i for k, i in self.turns.items() if i < index}
        self.emit({"type": "rewind", "itemId": item_id})
        self.emit({"type": "user", "message": {**message, "ts": db.now_ms()}})
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
            self._pick_up_queue()

    def _message(self, message_id: str, text: str, uploaded: list[dict[str, Any]]) -> dict:
        return {
            "id": message_id,
            "role": "user",
            "text": text,
            "ts": db.now_ms(),
            "files": [{"name": a["name"], "kind": a["kind"]} for a in uploaded],
        }

    def _push_turn(self, turn_id: str, content: Any) -> None:
        self.turns[turn_id] = len(self.messages)
        self.messages.append({"role": "user", "content": stamped(content)})
        self.persist()

    def _deliver_queued(self, starting_turn: bool = False) -> None:
        with self._lock:
            steered = [q for q in self._queue if q[0]["id"] not in self._held]
            ready = steered or (self._queue[:1] if starting_turn and self._startable() else [])
            self._queue = [q for q in self._queue if q not in ready]
            self._held -= {q[0]["id"] for q in ready}
        for message, uploaded in ready:
            self.emit({"type": "user", "message": {**message, "ts": db.now_ms()}})
            self._push_turn(message["id"], self._user_content(message["text"], uploaded))
        self._settle_queue()

    def _copy_uploads(self, files: list[dict[str, str]], turn_id: str) -> list[dict[str, Any]]:
        target_dir = attachments_dir(self.id)
        copied = []
        for item in files:
            if not item.get("id") or not item.get("name"):
                raise RunError("Each attached file needs an id and a name.")
            source = within(uploads_dir(), str(item["id"]))
            if not source.is_file():
                raise RunError(f"Upload not found: {item['name']}")

            target = unique_path(target_dir, str(item["name"]))
            shutil.move(source, target)
            copied.append(describe(target, "upload"))

        db.add_attachments(self.id, turn_id, [item["name"] for item in copied])
        return copied

    def _user_content(self, text: str, uploaded: list[dict[str, Any]]) -> Any:
        if not uploaded:
            return text

        lines = [f"{a['name']} ({a['kind']}, {a['size']} bytes)" for a in uploaded]
        body = f"{text or 'See the attached files.'}\n\nAttached files (open with run_read):\n" + "\n".join(
            f"- {line}" for line in lines
        )

        images = [a for a in uploaded if a["name"].lower().endswith(tuple(IMAGE_EXTS))]
        if not images or not self.vision:
            return body

        parts: list[dict[str, Any]] = [{"type": "text", "text": body}]
        for image in images:
            self.opened.add(image["name"])
            path = attachments_dir(self.id) / image["name"]
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_mime(path)};base64,{data}"},
                }
            )
        return parts

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
        self._set_status("running" if self._background_live() else "done")

    def _background_live(self) -> bool:
        with self._lock:
            return bool(self._background_tasks())

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
        return _uid("a")

    def mark_cut_off(self, call_ids: set[str]) -> None:
        self._cut_off.update(call_ids)

    def take_images(self) -> list[tuple[str, str]]:
        with self._lock:
            images, self._pending_images = self._pending_images, []
        return images

    def call_tool_named(self, name: str, args: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
        call = {"id": _uid("c"), "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        output = self.call_tool(call)
        return output, self.take_images()

    def call_tool_with_steering(self, name: str, args: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
        output, images = self.call_tool_named(name, args)
        with self._lock:
            ready = [q for q in self._queue if q[0]["id"] not in self._held]
            self._queue = [q for q in self._queue if q not in ready]
        if not ready:
            return output, images

        texts = []
        for message, uploaded in ready:
            self.emit({"type": "user", "message": {**message, "ts": db.now_ms()}})
            content = self._user_content(message["text"], uploaded)
            parts = content if isinstance(content, list) else [{"type": "text", "text": content}]
            texts += [p["text"] for p in parts if p["type"] == "text"]
            images += [(message["id"], p["image_url"]["url"]) for p in parts if p["type"] == "image_url"]
        self._settle_queue()
        return f"{output}\n\n{STEERED.format(text=chr(10).join(texts))}", images

    def call_tool(self, call: dict[str, Any]) -> str:
        self._local.tool = call["id"]
        try:
            tool, args = self._parsed_call(call)
        except ToolError as exc:
            return f"Error: {exc}"
        if tool.silent:
            return self._call_silent(tool, args)

        try:
            task = self._start_task(call["id"], tool, args)
        except RunError as exc:
            return f"Error: {exc}"

        task.settled.wait()
        with self._lock:
            if task.backgrounded_at is not None:
                return BACKGROUND_STARTED.format(label=task.label)
            return task.result

    def _parsed_call(self, call: dict[str, Any]) -> tuple[Tool, dict[str, Any]]:
        if call["id"] in self._cut_off:
            raise ToolError(CUT_OFF_ARGUMENTS)

        name = call["function"]["name"]
        tool = tool_named(name)
        if tool is None:
            raise ToolError(f"unknown tool {name}")
        return tool, _tool_args(tool, call["function"]["arguments"])

    def _call_silent(self, tool: Tool, args: dict[str, Any]) -> str:
        try:
            return tool.handler(args, self)
        except Exception as exc:
            return f"Error: {str(exc) or type(exc).__name__}"

    def _start_task(self, call_id: str, tool: Tool, args: dict[str, Any]) -> Task:
        background = args.pop("background", False) is True
        base = {
            "id": call_id,
            "name": tool.name,
            "label": tool.label(args),
            "input": json.dumps(args, indent=2)[:TOOL_INPUT_CHARS],
        }
        task = Task(base, db.now_ms())

        with self._lock:
            if background:
                self._check_background_room()
                task.backgrounded_at = task.started_at
                task.settled.set()
            self._tasks[task.id] = task

        running = {**base, "status": "running", "startedAt": task.started_at}
        if task.backgrounded_at is not None:
            running["backgroundedAt"] = task.backgrounded_at

        self.emit({"type": "tool", "tool": running})
        self._spawn(self._work, tool, args, task)
        return task

    def _work(self, tool: Tool, args: dict[str, Any], task: Task) -> None:
        self._local.tool = task.id
        try:
            output = tool.handler(args, TaskContext(self, task))
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self._finish_task(task, "error", message, f"Error: {message}")
            return
        self._finish_task(task, "ok", output, output)

    def _finish_task(self, task: Task, status: str, output: str, result: str) -> None:
        if task.stopped_at is not None:
            status, output, result = "error", STOPPED_BY_USER, f"Error: {STOPPED_BY_USER}"
        limit = TOOL_OUTPUT_CHARS if status == "ok" else TOOL_ERROR_CHARS
        done = {**task.tool, "status": status, "ms": db.now_ms() - task.started_at, "output": output[:limit]}
        if task.stopped_at is not None:
            done["stoppedAt"] = task.stopped_at

        self.emit({"type": "tool", "tool": done})

        with self._lock:
            task.result, task.finished = result, True
            del self._tasks[task.id]
            deliver = task.backgrounded_at is not None and task.stopped_at is None
            if deliver:
                self._finished_tasks.append(task)

        task.settled.set()
        if deliver:
            self._pick_up_queue()
        else:
            self._settle_if_quiet()

    def _settle_if_quiet(self) -> None:
        with self._lock:
            quiet = not (self._busy or self._finished_tasks or self._background_tasks())
        if quiet and self.state["summary"]["status"] == "running":
            self._set_status("done")

    def _background_tasks(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.backgrounded_at is not None]

    def _tool_done(self, base: dict[str, Any], status: str, started: int, output: str) -> None:
        tool = {**base, "status": status, "ms": db.now_ms() - started, "output": output}
        self.emit({"type": "tool", "tool": tool})

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
            self._pick_up_queue()

    def compaction_started(self, trigger: str) -> None:
        with self._lock:
            if self._compacting is not None:
                return
            self._compacting = {"id": _uid("k"), "trigger": trigger, "status": "running", "startedAt": db.now_ms()}
            entry = dict(self._compacting)
        self.emit({"type": "compact", "compact": entry})

    def compaction_finished(self, trigger: str, before: int, after: int) -> None:
        with self._lock:
            entry, self._compacting = self._compacting or {"id": _uid("k"), "startedAt": db.now_ms()}, None
        done = {**entry, "trigger": trigger, "status": "done", "before": before, "after": after}
        self.emit({"type": "compact", "compact": {**done, "ms": db.now_ms() - entry["startedAt"]}})

    def compaction_failed(self, error: str) -> None:
        with self._lock:
            entry, self._compacting = self._compacting, None
        if entry is not None:
            self.emit({"type": "compact", "compact": {**entry, "status": "error", "error": error}})

    def history_text(self) -> str:
        with self._lock:
            lines = [_history_line(self.state, item) for item in self.state["items"]]
        text = "\n\n".join(line for line in lines if line)
        if len(text) <= CONTINUE_TRANSCRIPT_CHARS:
            return text

        first = next((line for line in lines if line.startswith(HISTORY_USER)), "")
        return f"{first}\n\n{HISTORY_GAP}\n\n{text[-CONTINUE_TRANSCRIPT_CHARS:]}"

    def carry_over(self, source_title: str, history: str) -> None:
        self._busy = True
        self._spawn(self._carry_over, source_title, history)

    def _summary_of(self, history: str) -> str:
        summary, usage = self.agent.summarize(self.model, f"<conversation>\n{history}\n</conversation>")
        self.record_usage(self.model, UsageKind.COMPACT, usage)
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
            self.emit({"type": "message", "messageId": self.new_message_id(), "text": shown, "ts": db.now_ms()})
            self._set_status("done")
        except Exception as exc:
            self._fail(exc)
        finally:
            self._busy = False
            self._pick_up_queue()


def _history_line(state: dict[str, Any], item: dict[str, Any]) -> str:
    kind, item_id = item["kind"], item["id"]
    if kind in ("user", "text"):
        message = next((m for m in state["chat"] if m["id"] == item_id), None)
        speaker = HISTORY_USER if kind == "user" else HISTORY_AGENT
        return f"{speaker}\n{message['text']}" if message and message["text"].strip() else ""

    if kind == "tool":
        tool = next((t for t in state["tools"] if t["id"] == item_id), None)
        if tool is None:
            return ""
        output = (tool.get("output") or "")[: compaction.TRANSCRIPT_TOOL_CHARS]
        return f"Agent called {tool['name']} ({tool.get('label') or ''}):\n{output}"

    if kind == "question":
        question = next((q for q in state["questions"] if q["id"] == item_id), None)
        return f"Agent asked: {question_text(question)}" if question else ""

    if kind == "outcome" and state.get("outcome"):
        return f"{HISTORY_AGENT}\n{state['outcome'].get('reply') or ''}"
    return ""


def _tool_args(tool: Tool, raw: str) -> dict[str, Any]:
    try:
        args = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise ToolError(f"arguments are not valid JSON: {raw[:BAD_ARGS_CHARS]}") from None

    if not isinstance(args, dict):
        raise ToolError("arguments must be a JSON object.")

    missing = [key for key in tool.required if key not in args]
    if missing:
        raise ToolError(f"missing required arguments: {', '.join(missing)}")
    return args


def _check_answers(question: dict[str, Any], answers: list[str]) -> None:
    if question["kind"] == "approval":
        if answers not in APPROVAL_ANSWERS:
            raise RunError(f"Answer an approval with {APPROVE} or {REJECT}.")
        return
    if len(answers) != len(question["items"]) or not all(a.strip() for a in answers):
        raise RunError(f"Answer all {len(question['items'])} questions.")


def _line_changes(before: str, after: str) -> tuple[int, int]:
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, before.splitlines(), after.splitlines(), autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            removed += i2 - i1
            added += j2 - j1
    return added, removed


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


def short_title(text: str, limit: int) -> str:
    words = " ".join(text.split())
    if len(words) <= limit:
        return words
    head = words[:limit]
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip(_TITLE_NOISE)


def clean_title(reply: str) -> str:
    line = next((x for x in reply.splitlines() if x.strip()), "")
    title = _TITLE_PREFIX.sub("", line.strip().strip(_TITLE_NOISE)).strip(_TITLE_NOISE)
    return short_title(" ".join(title.split()[:MAX_TITLE_WORDS]), TITLE_CHARS)


def _base36(value: int) -> str:
    out = ""
    while value:
        value, rest = divmod(value, len(BASE36_DIGITS))
        out = BASE36_DIGITS[rest] + out
    return out or "0"


runs = RunManager()
