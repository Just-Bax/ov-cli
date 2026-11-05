from __future__ import annotations

import base64
import re
import shutil
from typing import Any

from ov.agent.engine.files import (
    IMAGE_EXTS,
    attachments_dir,
    describe,
    image_mime,
    unique_path,
    uploads_dir,
    within,
)
from ov.agent.engine.prompt import stamped
from ov.agent.engine.run_common import RunError
from ov.agent.storage import db

STEERED = "[The user wrote while you worked: {text}]"
MESSAGE_ID = re.compile(r"^u_[A-Za-z0-9_]{6,64}$")


class QueueMixin:
    def _restore_queue(self) -> None:
        for message in self.state["queued"]:
            self._queue.append((message, self._attached(message)))

        self._queue_held = bool(self._queue)
        self.state["queueHeld"] = self._queue_held

        undelivered = set(self.state["steering"])
        self._steers = [(m, self._attached(m)) for m in self.state["chat"] if m["id"] in undelivered]

    def _attached(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        return [describe(attachments_dir(self.id) / f["name"], "upload") for f in message.get("files") or []]

    def follow_up(self, message_id: str, text: str, files: list[dict[str, str]], steer: bool) -> None:
        self._check_new_id(message_id)
        claimed = self._claim()
        if claimed and not self.messages:
            self._busy = False
            raise RunError("This run has no conversation to continue.")

        try:
            uploaded = self._copy_uploads(files)
            message = self._message(message_id, text, uploaded)
            content = self._user_content(text, uploaded) if claimed else None
        except Exception:
            if claimed:
                self._busy = False
            raise

        if claimed:
            self._start_with(message, content)
            return

        if steer:
            self._steer(message, uploaded)
            return

        with self._lock:
            self._queue.append((message, uploaded))
        self.emit({"type": "queue_add", "message": message})
        self._pick_up_queue()

    def _start_with(self, message: dict[str, Any], content: Any) -> None:
        self._push_steers()
        self.name_branch(message["text"])
        self.emit({"type": "user_message", "message": message})
        self._push_turn(message["id"], content)
        self._spawn(self._run_turn)

    def _steer(self, message: dict[str, Any], uploaded: list[dict[str, Any]]) -> None:
        with self._lock:
            self._steers.append((message, uploaded))
        self.emit({"type": "user_message", "message": {**message, "steer": True, "ts": db.now_ms()}})
        self._emit_queue()
        self._pick_up_queue()

    def _check_new_id(self, message_id: str) -> None:
        if not MESSAGE_ID.match(message_id):
            raise RunError(f"A message id looks like u_<letters, digits or _>, not {message_id!r}.")

        with self._lock:
            known = any(m["id"] == message_id for m in self.state["chat"]) or any(
                q[0]["id"] == message_id for q in self._queue
            )
        if known:
            raise RunError("That message was already sent.")

    def _startable(self) -> bool:
        return (bool(self._queue) and not self._queue_held) or (bool(self._steers) and not self.cancel.is_set())

    def _pick_up_queue(self) -> None:
        with self._lock:
            waiting = self._startable() or bool(self._finished_tasks)
            woken_by = self._finished_tasks[0].id if self._finished_tasks and not self._startable() else None
        if waiting and self._claim():
            self._spawn(self._run_turn, woken_by)

    def remove_queued(self, message_id: str) -> None:
        with self._lock:
            self._queue = [q for q in self._queue if q[0]["id"] != message_id]
        self.emit({"type": "queue_remove", "id": message_id})
        self._settle_queue()

    def send_queued(self, message_id: str) -> None:
        with self._lock:
            entry = self._queued(message_id)
            self._queue = [q for q in self._queue if q is not entry]
        self._settle_queue()

        message, uploaded = entry
        if self._claim():
            self._start_with({**message, "ts": db.now_ms()}, self._user_content(message["text"], uploaded))
            return

        self._steer(message, uploaded)

    def edit_queued(self, message_id: str, text: str) -> None:
        with self._lock:
            message, uploaded = self._queued(message_id)
            if not text.strip() and not uploaded:
                raise RunError("A queued message needs text or files.")

            edited = {**message, "text": text}
            self._queue = [(edited, uploaded) if q[0]["id"] == message_id else q for q in self._queue]
        self.emit({"type": "queue_add", "message": edited})

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
            steering = [m["id"] for m, _ in self._steers]
            held = self._queue_held
        self.emit({"type": "queue_order", "order": order, "steering": steering, "held": held})

    def _queued(self, message_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        entry = next((q for q in self._queue if q[0]["id"] == message_id), None)
        if entry is None:
            raise RunError("That message is no longer queued.")
        return entry

    def _steering(self) -> bool:
        with self._lock:
            return bool(self._steers)

    def has_news(self) -> bool:
        with self._lock:
            return self._steering() or bool(self._finished_tasks)

    def _take_steers(self) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        with self._lock:
            steers, self._steers = self._steers, []
        if steers:
            self._emit_queue()
        return steers

    def _push_steers(self) -> None:
        for message, uploaded in self._take_steers():
            self._push_turn(message["id"], self._user_content(message["text"], uploaded))

    def _deliver_queued(self, starting_turn: bool = False) -> None:
        if self._steering():
            self._push_steers()
            return
        if not starting_turn:
            return

        with self._lock:
            ready = self._queue[:1] if not self._queue_held else []
            self._queue = self._queue[len(ready) :]
        for message, uploaded in ready:
            self.emit({"type": "user_message", "message": {**message, "ts": db.now_ms()}})
            self._push_turn(message["id"], self._user_content(message["text"], uploaded))
        self._settle_queue()

    def call_tool_with_steering(self, name: str, args: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
        output, images = self.call_tool_named(name, args)
        steers = self._take_steers()
        if not steers:
            return output, images

        texts = []
        for message, uploaded in steers:
            content = self._user_content(message["text"], uploaded)
            parts = content if isinstance(content, list) else [{"type": "text", "text": content}]
            texts += [p["text"] for p in parts if p["type"] == "text"]
            images += [(message["id"], p["image_url"]["url"]) for p in parts if p["type"] == "image_url"]
        return f"{output}\n\n{STEERED.format(text=chr(10).join(texts))}", images

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
            shutil.move(source, target)
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
