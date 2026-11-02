from __future__ import annotations

import json
import queue
from collections.abc import Callable
from typing import Any

from ov.agent.engine.feed import status_feed
from ov.agent.engine.links import links_for, seen_ids
from ov.agent.engine.state import details, reduce, search, snapshot, window
from ov.agent.instances.ovproc import find_instance
from ov.agent.integrations.common import Usage
from ov.agent.storage import db

WAKE_STATUSES = ("waiting", "error", "done")


class EventsMixin:
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
                backlog.append({"seq": self.seq, "ts": db.now_ms(), "live": True, "event": _message_event(partial)})

        def unsubscribe() -> None:
            with self._lock:
                if channel in self._listeners:
                    self._listeners.remove(channel)
                self.touched = db.now_ms()

        return channel, unsubscribe, backlog

    def stream_text(self, message_id: str, delta: str) -> None:
        self._stream_delta("text", message_id, delta)

    def stream_reasoning(self, message_id: str, delta: str) -> None:
        self._stream_delta("reasoning", message_id, delta)

    def _stream_delta(self, kind: str, message_id: str, delta: str) -> None:
        if self.cancel.is_set():
            return

        with self._lock:
            self._streaming = message_id

            live = {
                "seq": self.seq,
                "ts": db.now_ms(),
                "live": True,
                "event": {"type": kind, "messageId": message_id, "delta": delta},
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

        event = _message_event(message)

        with self._lock:
            seen = seen_ids(self.state, self.instance)
        linked = links_for(message["text"], seen, _base_urls(set(seen.values())))
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


def _message_event(message: dict[str, Any]) -> dict[str, Any]:
    event = {"type": "message", "messageId": message["id"], "text": message["text"], "ts": message["ts"]}
    if message.get("reasoning"):
        event["reasoning"] = message["reasoning"]
    return event


def _base_urls(refs: set[str]) -> dict[str, str]:
    found = {ref: find_instance(ref) for ref in refs if ref}
    return {ref: row["url"] for ref, row in found.items() if row is not None}
