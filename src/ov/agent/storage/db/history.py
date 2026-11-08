from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ov.agent.storage.db.clock import now_ms
from ov.agent.storage.db.engine import _begin
from ov.agent.storage.models import Event, EventType, Message


def append_event(thread_id: str, position: int, data: dict[str, Any]) -> dict[str, Any]:
    created = now_ms()
    kind = EventType(data["type"])
    body = {k: v for k, v in data.items() if k != "type"}

    with _begin() as conn:
        conn.execute(
            insert(Event).values(thread_id=thread_id, position=position, type=kind, data=body, created_at=created)
        )

    return {"seq": position, "ts": created, "event": data}


def load_events(thread_id: str, after: int = -1) -> list[dict[str, Any]]:
    query = select(Event.position, Event.type, Event.data, Event.created_at).where(
        Event.thread_id == thread_id, Event.position > after
    )
    with _begin() as conn:
        rows = conn.execute(query.order_by(Event.position)).all()
    return [{"seq": r.position, "ts": r.created_at, "event": {"type": r.type, **r.data}} for r in rows]


def load_messages(thread_id: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    query = select(Message).where(Message.thread_id == thread_id).order_by(Message.position)
    with _begin() as conn, Session(bind=conn) as session:
        rows = session.scalars(query).all()
    messages = [_message_dict(row) for row in rows]
    turns = {row.turn_id: row.position for row in rows if row.turn_id}
    return messages, turns


def _message_dict(row: Message) -> dict[str, Any]:
    message: dict[str, Any] = {"role": row.role, "content": row.content}
    if row.tool_calls is not None:
        message["tool_calls"] = row.tool_calls
    if row.tool_call_id is not None:
        message["tool_call_id"] = row.tool_call_id
    return message


def save_messages(thread_id: str, start: int, messages: list[dict[str, Any]], turns: dict[int, str]) -> None:
    created = now_ms()
    rows = [
        {
            "thread_id": thread_id,
            "position": start + offset,
            "role": message["role"],
            "content": message.get("content"),
            "tool_calls": message.get("tool_calls") or None,
            "tool_call_id": message.get("tool_call_id"),
            "turn_id": turns.get(start + offset),
            "created_at": created,
        }
        for offset, message in enumerate(messages)
    ]

    with _begin() as conn:
        conn.execute(delete(Message).where(Message.thread_id == thread_id, Message.position >= start))

        if rows:
            conn.execute(insert(Message), rows)
