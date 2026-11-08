from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select

from ov.agent.storage.db.engine import _begin
from ov.agent.storage.db.threads import summary_rows, thread_query
from ov.agent.storage.models import Event, EventType, Thread

SEARCHED_EVENTS = (EventType.USER_MESSAGE, EventType.AGENT_MESSAGE)
SEARCH_TEXT = {EventType.USER_MESSAGE: "$.message.text", EventType.AGENT_MESSAGE: "$.text"}
SEARCH_LIMIT = 20
SNIPPET_CHARS = 160
LIKE_ESCAPE = "\\"


def _like(query: str) -> str:
    escaped = (
        query.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", f"{LIKE_ESCAPE}%").replace("_", f"{LIKE_ESCAPE}_")
    )
    return f"%{escaped}%"


def _snippet(text: str, query: str) -> str:
    at = text.casefold().find(query.casefold())
    start = max(0, at - SNIPPET_CHARS // 2) if at >= 0 else 0
    piece = " ".join(text[start : start + SNIPPET_CHARS].split())
    return f"{'...' if start else ''}{piece}{'...' if start + SNIPPET_CHARS < len(text) else ''}"


def search_threads(query: str, limit: int = SEARCH_LIMIT) -> list[dict[str, Any]]:
    pattern = _like(query)
    text = case(
        *((Event.type == kind, func.json_extract(Event.data, path)) for kind, path in SEARCH_TEXT.items())
    ).label("text")
    hits = (
        select(Event.thread_id, text, Event.position)
        .join(Thread, Thread.id == Event.thread_id)
        .where(
            Event.type.in_(SEARCHED_EVENTS),
            Event.position >= Thread.inherited_until,
            text.like(pattern, escape=LIKE_ESCAPE),
        )
        .order_by(Event.thread_id, Event.position.desc())
    )

    with _begin() as conn:
        matched: dict[str, str] = {}
        for thread_id, found, _ in conn.execute(hits).all():
            matched.setdefault(thread_id, str(found))
        titled = conn.scalars(select(Thread.id).where(Thread.title.like(pattern, escape=LIKE_ESCAPE))).all()

    ids = set(matched) | set(titled)
    if not ids:
        return []

    summaries = summary_rows(thread_query().where(Thread.id.in_(ids)).order_by(Thread.updated_at.desc()).limit(limit))
    return [
        {**summary, "snippet": _snippet(matched.get(summary["id"], summary["title"]), query)} for summary in summaries
    ]
