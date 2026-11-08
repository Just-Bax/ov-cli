from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, literal, select
from sqlalchemy.dialects.sqlite import insert

from ov.agent.storage.db.engine import _begin
from ov.agent.storage.models import Event, EventType, Message, Origin

NOT_INHERITED = (
    EventType.STATUS,
    EventType.LOGIN,
    EventType.BROWSER,
    EventType.QUEUE_ADD,
    EventType.QUEUE_REMOVE,
    EventType.QUEUE_ORDER,
    EventType.CONTEXT,
)


@dataclass(frozen=True)
class Lineage:
    parent_id: str
    origin: Origin
    turn_id: str | None
    inherited_until: int


def turn_event_position(thread_id: str, turn_id: str) -> int | None:
    query = select(func.max(Event.position)).where(
        Event.thread_id == thread_id,
        Event.type == EventType.USER_MESSAGE,
        func.json_extract(Event.data, "$.message.id") == turn_id,
    )
    with _begin() as conn:
        return conn.scalar(query)


def copy_inherited(parent_id: str, child_id: str, *, until: int, messages: int) -> None:
    events = select(literal(child_id), Event.position, Event.type, Event.data, Event.created_at).where(
        Event.thread_id == parent_id, Event.position < until, Event.type.not_in(NOT_INHERITED)
    )
    history = select(
        literal(child_id),
        Message.position,
        Message.role,
        Message.content,
        Message.tool_calls,
        Message.tool_call_id,
        Message.turn_id,
        Message.created_at,
    ).where(Message.thread_id == parent_id, Message.position < messages)

    with _begin() as conn:
        event_columns = ["thread_id", "position", "type", "data", "created_at"]
        conn.execute(insert(Event).from_select(event_columns, events))
        message_columns = [
            "thread_id",
            "position",
            "role",
            "content",
            "tool_calls",
            "tool_call_id",
            "turn_id",
            "created_at",
        ]
        conn.execute(insert(Message).from_select(message_columns, history))
