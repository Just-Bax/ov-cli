from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, exists, func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import aliased

from ov.agent.storage.db.clock import now_ms
from ov.agent.storage.models import Event, EventType, Preference, Thread, ThreadStatus

PREFERENCE_ROW = 1
DEFAULT_MAX_STEPS = 80
DEFAULT_PROVIDER = "copilot"
INTERRUPTED_RUN = "Interrupted by a restart."
INTERRUPTED_TOOL = "Interrupted by a restart."
ACTIVE = (ThreadStatus.QUEUED, ThreadStatus.RUNNING, ThreadStatus.WAITING)

interrupted: list[str] = []


def prepare(conn: Connection) -> None:
    _close_orphans(conn)
    _ensure_preferences(conn)


def _append_next(conn: Connection, thread_id: str, kind: EventType, data: dict[str, Any]) -> None:
    position = conn.scalar(select(func.coalesce(func.max(Event.position), -1) + 1).where(Event.thread_id == thread_id))
    conn.execute(
        insert(Event).values(thread_id=thread_id, position=position, type=kind, data=data, created_at=now_ms())
    )


def _close_orphans(conn: Connection) -> None:
    orphans = conn.scalars(select(Thread.id).where(Thread.status.in_(ACTIVE))).all()
    for thread_id in orphans:
        _append_next(conn, thread_id, EventType.STATUS, {"status": ThreadStatus.ERROR, "error": INTERRUPTED_RUN})
    conn.execute(update(Thread).where(Thread.status.in_(ACTIVE)).values(status=ThreadStatus.ERROR))
    _close_open_tools(conn)
    interrupted.extend(orphans)


def _tool(entity: Any, path: str) -> Any:
    return func.json_extract(entity.data, f"$.tool.{path}")


def _close_open_tools(conn: Connection) -> None:
    later = aliased(Event)
    finished = exists().where(
        later.thread_id == Event.thread_id,
        later.position > Event.position,
        later.type == EventType.TOOL,
        _tool(later, "id") == _tool(Event, "id"),
        _tool(later, "status") != "running",
    )

    query = select(Event.thread_id, Event.data).where(
        Event.type == EventType.TOOL, _tool(Event, "status") == "running", ~finished
    )

    for thread_id, data in conn.execute(query).all():
        tool = {**data["tool"], "status": "error", "output": INTERRUPTED_TOOL}
        _append_next(conn, thread_id, EventType.TOOL, {"tool": tool})


def _ensure_preferences(conn: Connection) -> None:
    values = {
        "provider": DEFAULT_PROVIDER,
        "max_steps": DEFAULT_MAX_STEPS,
        "notify": False,
        "tab_badge": True,
        "compact_branches": False,
        "boost": False,
    }

    statement = insert(Preference).values(id=PREFERENCE_ROW, updated_at=now_ms(), **values)
    conn.execute(statement.on_conflict_do_nothing(index_elements=[Preference.id]))
