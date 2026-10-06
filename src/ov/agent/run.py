from __future__ import annotations

import base64
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
from .ovproc import login as ov_login
from .ovproc import url_for
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
from .state import empty_state, reduce
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
    "Name this OneVizion support request in 3 to 7 plain words, like a ticket title. "
    "Reply with the title only: no quotes, no trailing period."
)
RUN_ID_SUFFIX_CHARS = 4

WRITE_ON_NOTE = (
    "The user turned ON write access for this run. You may now apply changes with ov and the PagerDuty change "
    "tools (pd_note, pd_ack, pd_resolve, pd_escalate, pd_reassign, pd_snooze); each change still "
    "waits for their approval. Only apply what is needed."
)
WRITE_OFF_NOTE = "The user turned OFF write access for this run. Do not attempt changes; propose them instead."

_ids = itertools.count(1)


class RunError(Exception):
    pass


def _uid(prefix: str) -> str:
    return f"{prefix}_{db.now_ms()}_{next(_ids)}"


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
        self._messages = _answered(db.load_conversation(run_id) or [])
        self._turns: dict[str, dict[str, Any]] = db.load_conversation(f"{run_id}#turns") or {}
        self._pending_images: list[tuple[str, str]] = []
        self._notes: list[str] = []
        self._queue: list[tuple[dict[str, Any], Any]] = []
        self._questions: dict[str, tuple[threading.Event, list[str]]] = {}
        self._logins: dict[str, tuple[threading.Event, list[bool]]] = {}
        self._busy = False
        self._finished = False
        self._requests = 0
        self.deleted = False

    @property
    def instance(self) -> str:
        return self.state["summary"].get("instance") or ""

    def snapshot(self) -> str:
        with self._lock:
            return json.dumps(self.state)

    def subscribe(self) -> tuple[queue.Queue[dict[str, Any]], Callable[[], None]]:
        channel: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._listeners.append(channel)

        def unsubscribe() -> None:
            with self._lock:
                if channel in self._listeners:
                    self._listeners.remove(channel)

        return channel, unsubscribe

    def emit(self, event: dict[str, Any]) -> None:
        with self._lock:
            if self.deleted:
                return
            self.seq += 1
            stored = db.append_event(self.id, self.seq, event)
            reduce(self.state, stored)
            kind = event["type"]
            if kind == "status":
                db.update_run(self.id, status=event["status"])
            elif kind == "meta":
                db.update_run(self.id, title=event.get("title"), instance=event.get("instance"))
            elif kind in ("outcome", "rewind"):
                db.update_run(self.id, saved_minutes=self._saved_minutes())
            for channel in self._listeners:
                channel.put(stored)

    def _saved_minutes(self) -> int:
        outcome = self.state.get("outcome")
        return int(outcome["timeSaved"]["minutes"]) if outcome else 0

    def _save(self, key: str, value: Any) -> None:
        if not self.deleted:
            db.save_conversation(key, value)

    def _set_status(self, status: str, error: str | None = None) -> None:
        if self.state["summary"]["status"] == status and not error:
            return
        event: dict[str, Any] = {"type": "status", "status": status}
        if error:
            event["error"] = error
        self.emit(event)

    def _claim(self) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            self.cancel = Cancel()
            return True

    def _spawn(self, target: Callable[..., None], *args: Any) -> None:
        threading.Thread(target=target, args=args, daemon=True, name=f"run-{self.id}").start()

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

        for message, _ in dropped:
            self.emit({"type": "unqueue", "id": message["id"]})
        for event, answer in questions.values():
            answer.append("(cancelled)")
            event.set()
        for event, ok in logins.values():
            ok.append(False)
            event.set()

    def answer(self, question_id: str, answer: str) -> None:
        question = next((q for q in self.state["questions"] if q["id"] == question_id), None)
        with self._lock:
            waiter = self._questions.pop(question_id, None)
        if question is None or waiter is None:
            raise RunError("No such pending question.")

        self.emit({"type": "question", "question": {**question, "answer": answer}})
        waiter[1].append(answer)
        waiter[0].set()

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
        self._set_status("waiting")
        event.wait()
        self.cancel.check()
        self._set_status("running")
        return holder[0]

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

        self._set_status("waiting")
        waiter[0].wait()
        self.cancel.check()
        self._set_status("running")
        return waiter[1][0]

    def login(self, login_id: str, skip: bool) -> None:
        prompt = next((item for item in self.state["logins"] if item["id"] == login_id), None)
        if prompt is None:
            raise RunError("No such login prompt.")
        if skip:
            self.emit({"type": "login", "login": {**prompt, "state": "failed", "message": "Skipped"}})
            self._resolve_login(login_id, False)
            return

        self.emit({"type": "login", "login": {**prompt, "state": "running"}})
        result = ov_login(prompt["url"], prompt.get("tenant") or "")
        ok = result.code == 0
        update = {**prompt, "state": "done" if ok else "failed"}
        if not ok:
            update["message"] = result.message[-LOGIN_MESSAGE_CHARS:] or "Sign-in failed."
        self.emit({"type": "login", "login": update})
        if ok:
            self._resolve_login(login_id, True)

    def _resolve_login(self, login_id: str, ok: bool) -> None:
        with self._lock:
            waiter = self._logins.pop(login_id, None)
        if waiter is not None:
            waiter[1].append(ok)
            waiter[0].set()

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

    def follow_up(self, text: str, files: list[dict[str, str]]) -> None:
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
            self.emit({"type": "queued", "message": message})
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
        title = copilot.complete(model, NAMING_PROMPT, text[:NAMING_INPUT_CHARS]).strip("\"' .")
        if title and self.state["summary"]["title"] == placeholder:
            self.rename(title)

    def rename(self, title: str) -> None:
        cleaned = " ".join(title.split())[:TITLE_CHARS]
        if not cleaned:
            raise RunError("A run needs a name.")
        self.emit({"type": "meta", "title": cleaned})

    def remove_queued(self, message_id: str) -> None:
        with self._lock:
            self._queue = [q for q in self._queue if q[0]["id"] != message_id]
        self.emit({"type": "unqueue", "id": message_id})

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

    def _deliver_queued(self) -> None:
        with self._lock:
            ready, self._queue = self._queue, []
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
        if self.cancel.is_set():
            self._set_status("cancelled")
            return
        self._set_status("error", str(exc) or type(exc).__name__)

    def _loop(self, initiator: str) -> None:
        model = self.state["summary"]["model"]
        max_steps = int(db.get_settings()["maxSteps"])
        self.vision = copilot.supports_vision(model)
        self._finished = False
        for step in range(max_steps):
            self._prepare_step()
            specs = tool_specs(self.can_write())
            calls = self._ask_model(model, specs, initiator if step == 0 else "agent")
            if calls:
                self._run_tools(calls)
                if self._finished and not self._queue:
                    break
            elif not self._queue:
                break

        self._set_status("done")

    def _prepare_step(self) -> None:
        self.cancel.check()
        self._compact()
        if self._notes:
            notes, self._notes = self._notes, []
            self._messages.append({"role": "user", "content": f"[{' '.join(notes)}]"})
        if self._queue:
            self._deliver_queued()
            self._finished = False

    def _ask_model(self, model: str, specs: list[dict[str, Any]], initiator: str) -> list[dict[str, Any]]:
        message_id = _uid("a")
        result = copilot.stream_chat(
            model,
            self._messages,
            specs,
            initiator,
            cancel=self.cancel,
            on_text=lambda delta: self.emit({"type": "text", "messageId": message_id, "delta": delta}),
        )
        self._requests += 1
        self.emit({"type": "usage", "requests": self._requests})

        reply: dict[str, Any] = {"role": "assistant", "content": result.text or None}
        if result.tool_calls:
            reply["tool_calls"] = result.tool_calls
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
        run.begin(stored[1])
        return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            live = self._runs.get(run_id)
            if live is not None:
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
            self._runs[run_id] = run
            return run

    def delete(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.pop(run_id, None)
        if run is not None:
            run.deleted = True
            run.stop()
        db.delete_run(run_id)
        directory = run_dir(run_id)
        if directory.exists():
            shutil.rmtree(directory)


def _base36(value: int) -> str:
    digits = string.digits + string.ascii_lowercase
    out = ""
    while value:
        value, rest = divmod(value, 36)
        out = digits[rest] + out
    return out or "0"


runs = RunManager()
