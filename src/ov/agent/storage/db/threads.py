from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ov.agent.storage.db.clock import now_ms
from ov.agent.storage.db.engine import _begin
from ov.agent.storage.db.lineage import Lineage
from ov.agent.storage.db.usage import amounts
from ov.agent.storage.models import Access, Thread, ThreadStatus, Usage

RUN_LIST_LIMIT = 500
THREAD_COLUMNS = ("title", "instance", "status", "access")
ATTENTION_OF_STATUS = {ThreadStatus.DONE: "done", ThreadStatus.ERROR: "failed"}


def thread_query() -> Any:
    usage_of_thread = Usage.thread_id == Thread.id
    return select(
        Thread,
        select(func.sum(Usage.cost_nano)).where(usage_of_thread).scalar_subquery().label("nano"),
        select(func.count()).where(usage_of_thread).scalar_subquery().label("requests"),
    )


def _unseen_since(thread: Thread, moment: int | None) -> bool:
    return moment is not None and (thread.seen_at is None or thread.seen_at < moment)


def _attention(thread: Thread) -> str | None:
    snoozed = thread.snoozed_until
    if snoozed is not None and snoozed <= now_ms() and _unseen_since(thread, snoozed):
        return "woke"
    if not _unseen_since(thread, thread.status_changed_at):
        return None
    return ATTENTION_OF_STATUS.get(thread.status)


def _summary(thread: Thread, nano: int | None, requests: int) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": thread.id,
        "title": thread.title,
        "status": thread.status,
        "provider": thread.provider,
        "model": thread.model,
        "createdAt": thread.created_at,
        "updatedAt": thread.updated_at,
    }

    optional = {
        "instance": thread.instance,
        "parentId": thread.parent_id,
        "origin": thread.origin,
        "originTurnId": thread.origin_turn_id,
        "inheritedUntil": thread.inherited_until,
    }
    summary.update({key: value for key, value in optional.items() if value})

    if thread.settled_at:
        summary["settled"] = True
    if thread.pinned_at:
        summary["pinned"] = True
    if thread.snoozed_until and thread.snoozed_until > now_ms():
        summary["snoozedUntil"] = thread.snoozed_until

    attention = _attention(thread)
    if attention:
        summary["attention"] = attention

    if requests:
        summary["cost"] = amounts(nano, requests)

    return summary


def summary_rows(query: Any) -> list[dict[str, Any]]:
    with _begin() as conn, Session(bind=conn) as session:
        return [_summary(*row) for row in session.execute(query).all()]


def create_thread(
    thread_id: str,
    title: str,
    provider: str,
    model: str,
    *,
    instance: str | None,
    access: Access,
    lineage: Lineage | None = None,
) -> dict[str, Any]:
    now = now_ms()
    values = {
        "title": title,
        "provider": provider,
        "model": model,
        "instance": instance,
        "access": access,
        "parent_id": lineage.parent_id if lineage else None,
        "origin": lineage.origin if lineage else None,
        "origin_turn_id": lineage.turn_id if lineage else None,
        "inherited_until": lineage.inherited_until if lineage else 0,
    }

    with _begin() as conn:
        conn.execute(
            insert(Thread).values(id=thread_id, status=ThreadStatus.QUEUED, created_at=now, updated_at=now, **values)
        )

    summary = get_thread(thread_id)
    if summary is None:
        raise ValueError(f"Thread {thread_id} was not saved.")
    return summary


def update_thread(thread_id: str, **patch: Any) -> None:
    unknown = set(patch) - set(THREAD_COLUMNS)
    if unknown:
        raise ValueError(f"Threads have no {', '.join(sorted(unknown))}.")

    values = {k: v for k, v in patch.items() if v is not None}
    now = now_ms()
    if "status" in values:
        values["status_changed_at"] = now

    with _begin() as conn:
        conn.execute(update(Thread).where(Thread.id == thread_id).values(updated_at=now, **values))


def list_threads(settled: bool | None = None, limit: int = RUN_LIST_LIMIT) -> list[dict[str, Any]]:
    query = thread_query()
    if settled is not None:
        query = query.where(Thread.settled_at.is_not(None) if settled else Thread.settled_at.is_(None))
    return summary_rows(query.order_by(Thread.updated_at.desc()).limit(limit))


def get_thread(thread_id: str) -> dict[str, Any] | None:
    found = summary_rows(thread_query().where(Thread.id == thread_id))
    return found[0] if found else None


def thread_access(thread_id: str) -> Access:
    with _begin() as conn:
        return Access(conn.scalar(select(Thread.access).where(Thread.id == thread_id)))


def delete_thread(thread_id: str) -> None:
    with _begin() as conn:
        conn.execute(delete(Thread).where(Thread.id == thread_id))


def child_threads(thread_id: str) -> list[dict[str, Any]]:
    return summary_rows(thread_query().where(Thread.parent_id == thread_id).order_by(Thread.created_at))


def _set_thread(thread_id: str, **values: Any) -> None:
    with _begin() as conn:
        conn.execute(update(Thread).where(Thread.id == thread_id).values(**values))


def set_pinned(thread_id: str, pinned: bool) -> None:
    _set_thread(thread_id, pinned_at=now_ms() if pinned else None)


def set_snoozed(thread_id: str, until: int | None) -> None:
    if until is not None and until <= now_ms():
        raise ValueError("Snooze until a time in the future.")
    _set_thread(thread_id, snoozed_until=until)


def set_seen(thread_id: str) -> None:
    _set_thread(thread_id, seen_at=now_ms())


def set_settled(thread_id: str, settled: bool) -> None:
    _set_thread(thread_id, settled_at=now_ms() if settled else None)


def settled_count() -> int:
    with _begin() as conn:
        return int(conn.scalar(select(func.count()).where(Thread.settled_at.is_not(None))) or 0)
