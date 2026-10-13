from __future__ import annotations

import base64
import difflib
import itertools
import json
import queue
import random
import shutil
import string
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import cases, copilot, db
from .cancel import Cancel
from .links import links_for, seen_ids
from .ovproc import find_instance, url_for
from .ovproc import login as ov_login
from .prompt import system_prompt
from .runfiles import (
    IMAGE_EXTS,
    attachments_dir,
    describe,
    image_mime,
    run_dir,
    unique_path,
    uploads_dir,
    within,
)
from .skills import reply_style
from .state import details, empty_state, reduce, search, snapshot, window
from .tools import Tool, ToolError, tool_named, tool_specs

CONTEXT_BUDGET = 360_000
COMPACT_TARGET = int(CONTEXT_BUDGET * 0.7)
KEEP_RECENT_MESSAGES = 12
TRIMMED_TOOL_OUTPUT = 1200
TOOL_WORKERS = 8
TOOL_INPUT_CHARS = 8000
TOOL_OUTPUT_CHARS = 12000
TOOL_ERROR_CHARS = 4000
BAD_ARGS_CHARS = 200
LOGIN_MESSAGE_CHARS = 300
TITLE_CHARS = 120
PROMPT_TITLE_CHARS = 90
NAMING_INPUT_CHARS = 2000
NAMING_PROMPT = (
    "You write titles for a list of conversations. You never answer or act on the request. "
    "Given the user's first message between <message> tags, reply with a 3 to 7 word title "
    "naming its topic, like a ticket title. Reply with the title only: one line, no quotes, no "
    "markdown, no trailing period."
)
MAX_TITLE_WORDS = 10
RUN_ID_SUFFIX_CHARS = 4
IDLE_EVICT_MS = 5 * 60_000
MAX_CACHED_RUNS = 6
EVICT_GRACE_MS = 60_000

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
WATCH_MIN_MINUTES = 5
WATCH_MAX_MINUTES = 240
WATCH_MAX_HOURS = 72
WATCH_RETRY_MS = MINUTE_MS
WATCH_SUFFIX = (
    "\n\n(Scheduled check. Check it, then answer in two or three sentences: what changed since the last "
    "check and whether it is resolved. If it is resolved or no longer worth checking, call run_watch with "
    "stop=true.)"
)
REPLY_PROMPT = (
    "Rewrite the engineer's findings below as the comment they will post to the customer on the support "
    "case. Use only facts in the findings; never add new ones. Output only the comment text."
)
REPLY_CONTEXT_CHARS = 2000
REPLY_MAX_TOKENS = 1500
EMPTY_REPLY_NOTE = "Your last reply was empty. Answer the user's last message."
WRITE_ON_NOTE = (
    "The user turned ON write access for this run. You may now apply changes with ov and the PagerDuty change "
    "tools (pd_note, pd_ack, pd_resolve, pd_escalate, pd_reassign, pd_snooze); each change still "
    "waits for their approval. Only apply what is needed."
)
WRITE_OFF_NOTE = "The user turned OFF write access for this run. Do not attempt changes; propose them instead."

STOPPED_ANSWER = "(not answered: the run stopped)"
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
    def __init__(self, run_id: str, state: dict[str, Any], seq: int) -> None:
        self.id = run_id
        self.state = state
        self.seq = seq
        self.work_dir = run_dir(run_id)
        self.cancel = Cancel()
        self.opened: set[str] = set()
        self.vision = True
        self._lock = threading.RLock()
        self._listeners: list[queue.Queue[dict[str, Any]]] = []
        self._loaded_messages: list[dict[str, Any]] | None = None
        self._loaded_turns: dict[str, dict[str, Any]] | None = None
        self._cut_off: set[str] = set()
        self._local = threading.local()
        self._pending_images: list[tuple[str, str]] = []
        self._notes: list[str] = []
        self._waits = 0
        self._queue: list[tuple[dict[str, Any], Any]] = []
        self._held: set[str] = set()
        self._questions: dict[str, tuple[threading.Event, list[str]]] = {}
        self._logins: dict[str, tuple[threading.Event, list[bool]]] = {}
        self._busy = False
        self._finished = False
        self._streaming: str | None = None
        self._background = 0
        self.touched = db.now_ms()

    @property
    def _messages(self) -> list[dict[str, Any]]:
        if self._loaded_messages is None:
            self._loaded_messages = _answered(db.load_conversation(self.id) or [])
        return self._loaded_messages

    @_messages.setter
    def _messages(self, messages: list[dict[str, Any]]) -> None:
        self._loaded_messages = messages

    @property
    def _turns(self) -> dict[str, dict[str, Any]]:
        if self._loaded_turns is None:
            self._loaded_turns = db.load_conversation(f"{self.id}#turns") or {}
        return self._loaded_turns

    @_turns.setter
    def _turns(self, turns: dict[str, dict[str, Any]]) -> None:
        self._loaded_turns = turns

    @property
    def instance(self) -> str:
        return self.state["summary"].get("instance") or ""

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

    def _stream_text(self, message_id: str, delta: str) -> None:
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

    def _commit_text(self, message_id: str) -> None:
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
                linked = links_for(message["text"], found["host"], seen_ids(self.state))
            if linked["mentions"] or linked["unverified"]:
                event["links"] = linked
        self.emit(event)

    def _record_usage(self, model: str, kind: str, usage: copilot.Usage | None) -> None:
        if usage is None:
            return
        cost = db.add_usage(self.id, model, kind, usage.tokens, usage.nano)
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
                db.update_run(self.id, status=event["status"])
            elif kind == "meta":
                db.update_run(self.id, title=event.get("title"), instance=event.get("instance"))
                status_feed.publish({"kind": "meta", "id": self.id})
            elif kind in ("outcome", "rewind"):
                db.update_run(self.id, saved_minutes=self._saved_minutes())
            for channel in self._listeners:
                channel.put(stored)

    def _saved_minutes(self) -> int:
        outcome = self.state.get("outcome")
        return int(outcome["timeSaved"]["minutes"]) if outcome else 0

    def _save(self, key: str, value: Any) -> None:
        db.save_conversation(key, value)

    def _set_status(self, status: str, error: str | None = None) -> None:
        with self._lock:
            if self.state["summary"]["status"] == status and not error:
                return
            event: dict[str, Any] = {"type": "status", "status": status}
            if error:
                event["error"] = error
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

    def set_write_access(self, write: bool) -> None:
        if self.state["writeAccess"] == write:
            return
        self.emit({"type": "access", "write": write})
        self._notes.append(WRITE_ON_NOTE if write else WRITE_OFF_NOTE)

    def stop(self) -> None:
        self.cancel.set()
        with self._lock:
            dropped, self._queue = self._queue, []
            questions, self._questions = self._questions, {}
            logins, self._logins = self._logins, {}

        self._held.clear()
        for message, _ in dropped:
            self.emit({"type": "unqueue", "id": message["id"]})
        for question_id, (event, answer) in questions.items():
            self._close_question(question_id, STOPPED_ANSWER)
            answer.append(STOPPED_ANSWER)
            event.set()
        for event, ok in logins.values():
            ok.append(False)
            event.set()

    def answer(self, question_id: str, answer: str) -> None:
        question = next((q for q in self.state["questions"] if q["id"] == question_id), None)
        with self._lock:
            waiter = self._questions.pop(question_id, None)
        if question is None:
            raise RunError("No such question in this run.")
        if waiter is None:
            self._close_question(question_id, STOPPED_ANSWER)
            raise RunError("The agent is no longer waiting for this answer. Send a message to continue.")

        self.emit({"type": "question", "question": {**question, "answer": answer}})
        waiter[1].append(answer)
        waiter[0].set()

    def _close_question(self, question_id: str, answer: str) -> None:
        question = next((q for q in self.state["questions"] if q["id"] == question_id), None)
        if question is not None and "answer" not in question:
            self.emit({"type": "question", "question": {**question, "answer": answer}})

    def ask_user(self, question: str, options: list[str], multiple: bool, detail: str | None = None) -> str:
        entry: dict[str, Any] = {
            "id": _uid("q"),
            "question": question,
            "options": options,
            "multiple": multiple,
        }
        if detail:
            entry["detail"] = detail

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
                    and item["state"] not in ("done", "failed")
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
        self, login_id: str, skip: bool, token: str = "", screen: tuple[int, int] | None = None
    ) -> dict[str, Any]:
        prompt = next((item for item in self.state["logins"] if item["id"] == login_id), None)
        if prompt is None:
            raise RunError("No such login prompt.")
        if skip:
            self.emit({"type": "login", "login": {**prompt, "state": "failed", "message": "Skipped"}})
            self._resolve_login(login_id, False)
            return {"ok": False, "message": "Skipped"}

        self.emit({"type": "login", "login": {**prompt, "state": "running"}})
        result = ov_login(prompt["url"], prompt.get("tenant") or "", token, screen)
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

    def can_write(self) -> bool:
        return bool(self.state["writeAccess"])

    def finish(self, outcome: dict[str, Any]) -> None:
        self._finished = True
        self.emit({"type": "outcome", "outcome": outcome})

    def begin(self, data: dict[str, Any]) -> None:
        self._busy = True
        self._spawn(self._start, data)

    def _start(self, data: dict[str, Any]) -> None:
        try:
            self._set_status("running")
            uploaded = self._copy_uploads(data.get("attachments") or [])
            text = (data.get("prompt") or "").strip()
            self.emit({"type": "user", "message": self._message("u_start", text, uploaded)})
            self.vision = copilot.supports_vision(self.state["summary"]["model"])

            ref = None if uploaded else cases.case_ref(text)
            if not ref and text:
                self._name_later(text)
            content = self._preload_case(ref) if ref else self._user_content(text, uploaded)
            self._messages = [{"role": "system", "content": system_prompt(self.can_write(), self.instance)}]
            self._push_turn("u_start", content)
            self._loop("user")
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
        return f"Troubleshoot this case.\n\n{text}"

    def load_case(self, ref: str) -> str:
        for attempt in range(2):
            try:
                bundle = cases.load_case(ref, self.work_dir, self.cancel)
                break
            except cases.NeedsLogin as exc:
                if attempt or not self.require_login(exc.host):
                    raise RunError(f"Not signed in to {exc.host}.") from None

        title = " ".join(bundle["title"].split()) or f"Case {bundle['key']}"
        self.emit(
            {
                "type": "meta",
                "title": f"{bundle['key']}: {title}"[:TITLE_CHARS],
                "caseKey": bundle["key"],
                "caseUrl": bundle["url"],
                "instance": bundle["website"],
            }
        )

        text = cases.render(bundle, self.work_dir)
        if bundle["website"]:
            text += f"\n\nThe run's default instance is now {bundle['website']}."
        return text

    def follow_up(self, text: str, files: list[dict[str, str]], steer: bool = True) -> None:
        claimed = self._claim()
        if claimed and not self._messages:
            self._busy = False
            raise RunError("This run has no conversation to continue.")

        try:
            uploaded = self._copy_uploads(files)
            message = self._message(_uid("u"), text, uploaded)
            content = self._user_content(text, uploaded)
        except Exception:
            if claimed:
                self._busy = False
            raise

        if not claimed:
            with self._lock:
                self._queue.append((message, content))
                if not steer:
                    self._held.add(message["id"])
            self.emit({"type": "queued", "message": {**message, "steer": steer}})
            self._pick_up_queue()
            return

        self.emit({"type": "user", "message": message})
        self._push_turn(message["id"], content)
        self._spawn(self._run_turn)

    def _pick_up_queue(self) -> None:
        with self._lock:
            waiting = bool(self._queue)
        if waiting and self._claim():
            self._spawn(self._run_turn)

    def rate(self, turn_id: str, rating: str | None, note: str | None) -> None:
        self.emit({"type": "rate", "turnId": turn_id, "rating": rating, "note": note})

    def _name_later(self, text: str) -> None:
        fast = db.get_settings()["fastModel"]
        if fast:
            self._spawn(self._name, fast, self.state["summary"]["title"], text)

    def _name(self, model: str, placeholder: str, text: str) -> None:
        reply, usage = copilot.complete(model, NAMING_PROMPT, f"<message>\n{text[:NAMING_INPUT_CHARS]}\n</message>")
        self._record_usage(model, "naming", usage)
        title = reply.strip().splitlines()[0].strip("\"'#*` .") if reply.strip() else ""
        if not title or len(title.split()) > MAX_TITLE_WORDS:
            return
        if self.state["summary"]["title"] == placeholder:
            self.rename(title)

    def draft_reply(self, message_id: str) -> str:
        answer = next((m for m in self.state["chat"] if m["id"] == message_id and m["role"] == "assistant"), None)
        if answer is None:
            raise RunError("No such agent message.")
        asked = next((m["text"] for m in self.state["chat"] if m["role"] == "user"), "")
        model = self.state["summary"]["model"]
        prompt = f"{REPLY_PROMPT}\n\n{reply_style()}"
        case = f"{self.state['summary']['title']}\n{asked[:REPLY_CONTEXT_CHARS]}"
        body = f"<case>\n{case}\n</case>\n\n<findings>\n{answer['text']}\n</findings>"
        text, usage = copilot.complete(model, prompt, body, REPLY_MAX_TOKENS)
        self._record_usage(model, "reply", usage)
        return text

    def rename(self, title: str) -> None:
        cleaned = " ".join(title.split())[:TITLE_CHARS]
        if not cleaned:
            raise RunError("A run needs a name.")
        self.emit({"type": "meta", "title": cleaned})

    def remove_queued(self, message_id: str) -> None:
        with self._lock:
            self._queue = [q for q in self._queue if q[0]["id"] != message_id]
            self._held.discard(message_id)
        self.emit({"type": "unqueue", "id": message_id})

    def watch(self, prompt: str, every_minutes: int, hours: float) -> dict[str, Any]:
        text = " ".join(prompt.split())
        if not text:
            raise RunError("Say what to check.")
        if not WATCH_MIN_MINUTES <= every_minutes <= WATCH_MAX_MINUTES:
            raise RunError(f"Check every {WATCH_MIN_MINUTES} to {WATCH_MAX_MINUTES} minutes.")
        if not 0 < hours <= WATCH_MAX_HOURS:
            raise RunError(f"Watch for up to {WATCH_MAX_HOURS} hours.")
        watch = db.set_watch(self.id, text, every_minutes * MINUTE_MS, db.now_ms() + int(hours * HOUR_MS))
        self.emit({"type": "watch", "watch": watch})
        return watch

    def unwatch(self) -> None:
        db.clear_watch(self.id)
        self.emit({"type": "watch", "watch": None})

    def fire_watch(self) -> None:
        watch = db.get_watch(self.id)
        if watch is None:
            return
        now = db.now_ms()
        if now >= watch["until"]:
            self.unwatch()
            return
        with self._lock:
            busy = self._busy or bool(self._queue)
        if busy:
            db.advance_watch(self.id, now + WATCH_RETRY_MS)
            return

        updated = db.advance_watch(self.id, now + watch["everyMs"])
        self.emit({"type": "watch", "watch": updated})
        total = watch["fired"] + 1 + max(0, (watch["until"] - now) // watch["everyMs"])
        self.follow_up(f"Watch check {watch['fired'] + 1} of about {total}: {watch['prompt']}{WATCH_SUFFIX}", [])

    def steer_queued(self, message_id: str) -> None:
        with self._lock:
            entry = next((q for q in self._queue if q[0]["id"] == message_id), None)
            if entry is None:
                raise RunError("That message is no longer queued.")
            self._held.discard(message_id)
        self.emit({"type": "queued", "message": {**entry[0], "steer": True}})

    def _steering(self) -> bool:
        with self._lock:
            return any(q[0]["id"] not in self._held for q in self._queue)

    def retry(self, item_id: str) -> None:
        turn = self._turns.get(item_id)
        message = next((m for m in self.state["chat"] if m["id"] == item_id and m["role"] == "user"), None)
        if turn is None or message is None:
            raise RunError("This message cannot be retried.")
        if not self._claim():
            raise RunError("Wait for the agent to finish, or stop it, before retrying.")

        self._messages = self._messages[: turn["index"]]
        self._turns = {k: t for k, t in self._turns.items() if t["index"] <= turn["index"]}
        self.emit({"type": "rewind", "itemId": item_id})
        self.emit({"type": "user", "message": {**message, "ts": db.now_ms()}})
        self._push_turn(item_id, turn["content"])
        self._spawn(self._run_turn)

    def _run_turn(self) -> None:
        try:
            self._set_status("running")
            self._deliver_queued(everything=True)
            self._loop("user")
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
        self._turns[turn_id] = {"index": len(self._messages), "content": content}
        self._save(f"{self.id}#turns", self._turns)
        self._messages.append({"role": "user", "content": content})

    def _deliver_queued(self, everything: bool = False) -> None:
        with self._lock:
            ready = [q for q in self._queue if everything or q[0]["id"] not in self._held]
            self._queue = [q for q in self._queue if q not in ready]
            self._held -= {q[0]["id"] for q in ready}
        for message, content in ready:
            self.emit({"type": "user", "message": {**message, "ts": db.now_ms()}})
            self._push_turn(message["id"], content)

    def _copy_uploads(self, files: list[dict[str, str]]) -> list[dict[str, Any]]:
        target_dir = attachments_dir(self.id)
        copied = []
        for item in files:
            if not item.get("id") or not item.get("name"):
                raise RunError("Each attached file needs an id and a name.")
            source = within(uploads_dir(), str(item["id"]))
            if not source.is_file():
                raise RunError(f"Upload not found: {item['name']}")

            target = unique_path(target_dir, str(item["name"]))
            shutil.copyfile(source, target)
            copied.append(describe(target, "upload"))
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
        for tool in [t for t in self.state["tools"] if t["status"] == "running"]:
            self.emit({"type": "tool", "tool": {"id": tool["id"], "status": "error", "output": "Interrupted."}})
        if self.cancel.is_set():
            self._set_status("cancelled")
            return
        self._set_status("error", str(exc) or type(exc).__name__)

    def _loop(self, initiator: str) -> None:
        model = self.state["summary"]["model"]
        max_steps = int(db.get_settings()["maxSteps"])
        self.vision = copilot.supports_vision(model)
        self._finished = False
        nudged = False
        for step in range(max_steps):
            self._prepare_step()
            specs = tool_specs(self.can_write())
            calls = self._ask_model(model, specs, initiator if step == 0 else "agent")
            if calls:
                self._run_tools(calls)
                if self._finished and not self._steering():
                    break
            elif not self._messages[-1].get("content") and not nudged:
                nudged = True
                self._notes.append(EMPTY_REPLY_NOTE)
            elif not self._steering():
                break

        self._set_status("done")

    def _prepare_step(self) -> None:
        self.cancel.check()
        if self._messages and self._messages[0]["role"] == "system":
            self._messages[0] = {"role": "system", "content": system_prompt(self.can_write(), self.instance)}
        self._compact()
        if self._notes:
            notes, self._notes = self._notes, []
            self._messages.append({"role": "user", "content": f"[{' '.join(notes)}]"})
        if self._steering():
            self._deliver_queued()
            self._finished = False

    def _ask_model(self, model: str, specs: list[dict[str, Any]], initiator: str) -> list[dict[str, Any]]:
        message_id = _uid("a")
        self._messages = _answered(self._messages)
        for message in self._messages:
            if message.get("tool_calls"):
                message["tool_calls"] = _repaired(message["tool_calls"])
        try:
            result = copilot.stream_chat(
                model,
                self._messages,
                specs,
                initiator,
                cancel=self.cancel,
                on_text=lambda delta: self._stream_text(message_id, delta),
                reasoning=copilot.reasoning_for(model, db.get_settings()["reasoning"]),
            )
        finally:
            self._commit_text(message_id)
        self._record_usage(model, "turn" if initiator == "user" else "step", result.usage)

        reply: dict[str, Any] = {"role": "assistant", "content": result.text or None}
        if result.tool_calls:
            self._cut_off.update(c["id"] for c in result.tool_calls if not _valid_arguments(c))
            reply["tool_calls"] = _repaired(result.tool_calls)
        self._messages.append(reply)
        self._save(self.id, self._messages)
        return result.tool_calls

    def _run_tools(self, calls: list[dict[str, Any]]) -> None:
        with ThreadPoolExecutor(max_workers=TOOL_WORKERS) as pool:
            outputs = list(pool.map(self._call_tool, calls))
        for call, content in zip(calls, outputs, strict=True):
            self._messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})

        if self._pending_images:
            images, self._pending_images = self._pending_images, []
            parts: list[dict[str, Any]] = [{"type": "text", "text": f"Attached: {', '.join(n for n, _ in images)}"}]
            parts += [{"type": "image_url", "image_url": {"url": url}} for _, url in images]
            self._messages.append({"role": "user", "content": parts})
        self._save(self.id, self._messages)

    def _call_tool(self, call: dict[str, Any]) -> str:
        self._local.tool = call["id"]
        if call["id"] in self._cut_off:
            return f"Error: {CUT_OFF_ARGUMENTS}"

        name = call["function"]["name"]
        tool = tool_named(name)
        if tool is None:
            return f"Error: unknown tool {name}"
        try:
            args = _tool_args(tool, call["function"]["arguments"])
        except ToolError as exc:
            return f"Error: {exc}"

        started = db.now_ms()
        base = {
            "id": call["id"],
            "name": name,
            "label": tool.label(args),
            "input": json.dumps(args, indent=2)[:TOOL_INPUT_CHARS],
        }
        if not tool.silent:
            self.emit({"type": "tool", "tool": {**base, "status": "running"}})
        try:
            content = tool.handler(args, self)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            if not tool.silent:
                self._tool_done(base, "error", started, message[:TOOL_ERROR_CHARS])
            return f"Error: {message}"

        if not tool.silent:
            self._tool_done(base, "ok", started, content[:TOOL_OUTPUT_CHARS])
        return content

    def _tool_done(self, base: dict[str, Any], status: str, started: int, output: str) -> None:
        tool = {**base, "status": status, "ms": db.now_ms() - started, "output": output}
        self.emit({"type": "tool", "tool": tool})

    def _compact(self) -> None:
        if _size(self._messages) < CONTEXT_BUDGET:
            return

        keep_from = max(2, len(self._messages) - KEEP_RECENT_MESSAGES)
        for message in self._messages[2:keep_from]:
            if _size(self._messages) <= COMPACT_TARGET:
                break
            _trim(message)


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


def _size(messages: list[dict[str, Any]]) -> int:
    return len(json.dumps(messages))


def _trim(message: dict[str, Any]) -> None:
    content = message["content"]
    if message["role"] == "tool" and len(content) > TRIMMED_TOOL_OUTPUT:
        message["content"] = content[:TRIMMED_TOOL_OUTPUT] + "\n[older output trimmed to save context]"
    elif message["role"] == "user" and isinstance(content, list):
        message["content"] = [
            {"type": "text", "text": "[image removed to save context]"} if part["type"] == "image_url" else part
            for part in content
        ]


def _line_changes(before: str, after: str) -> tuple[int, int]:
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, before.splitlines(), after.splitlines(), autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            removed += i2 - i1
            added += j2 - j1
    return added, removed


def _valid_arguments(call: dict[str, Any]) -> bool:
    try:
        return isinstance(json.loads(call["function"]["arguments"] or "{}"), dict)
    except json.JSONDecodeError:
        return False


def _repaired(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        call if _valid_arguments(call) else {**call, "function": {**call["function"], "arguments": "{}"}}
        for call in calls
    ]


def _answered(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixed: list[dict[str, Any]] = []
    pending: list[str] = []
    for message in messages:
        if message["role"] == "tool":
            if message["tool_call_id"] in pending:
                pending.remove(message["tool_call_id"])
            fixed.append(message)
            continue
        fixed += [_interrupted(call_id) for call_id in pending]
        pending = [c["id"] for c in message.get("tool_calls") or []]
        fixed.append(message)
    return fixed + [_interrupted(call_id) for call_id in pending]


def _interrupted(call_id: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": "Error: interrupted."}


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def create(self, data: dict[str, Any], model: str) -> Run:
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=RUN_ID_SUFFIX_CHARS))
        run_id = f"r{_base36(db.now_ms())}{suffix}"
        prompt = (data.get("prompt") or "").strip()
        title = (prompt.split("\n", 1)[0] or "Attached files")[:PROMPT_TITLE_CHARS]
        db.create_run(run_id, title, model, data)
        stored = db.get_run(run_id)
        if stored is None:
            raise RunError(f"Run {run_id} was not saved.")

        run = Run(run_id, empty_state(*stored), -1)
        with self._lock:
            self._runs[run_id] = run
        status_feed.publish({"kind": "list"})
        run.begin(stored[1])
        return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            live = self._runs.get(run_id)
            if live is not None:
                live.touched = db.now_ms()
                self._evict()
                return live

            stored = db.get_run(run_id)
            if stored is None:
                return None

            state = empty_state(*stored)
            events = db.load_events(run_id)
            for event in events:
                reduce(state, event)
            state["summary"] = {**state["summary"], **stored[0]}
            feedback = db.get_feedback(run_id)
            if feedback:
                state["feedback"] = feedback
            run = Run(run_id, state, events[-1]["seq"] if events else -1)
            self._evict()
            self._runs[run_id] = run
            return run

    def _evict(self) -> None:
        now = db.now_ms()
        idle = sorted(
            (r for r in self._runs.values() if r.idle() and now - r.touched > EVICT_GRACE_MS),
            key=lambda r: r.touched,
        )
        for run in idle:
            if now - run.touched > IDLE_EVICT_MS or len(self._runs) > MAX_CACHED_RUNS:
                del self._runs[run.id]


def _base36(value: int) -> str:
    digits = string.digits + string.ascii_lowercase
    out = ""
    while value:
        value, rest = divmod(value, 36)
        out = digits[rest] + out
    return out or "0"


runs = RunManager()
