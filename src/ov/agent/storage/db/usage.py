from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.sqlite import insert

from ov.agent.storage.db.clock import now_ms
from ov.agent.storage.db.engine import _begin
from ov.agent.storage.models import Thread, Usage

NANO_PER_UNIT = 1_000_000_000
TOP_THREADS = 5
TOKEN_COLUMNS = {
    "input": "input_tokens",
    "cache_read": "cache_read_tokens",
    "cache_write": "cache_write_tokens",
    "output": "output_tokens",
}


def amounts(nano: int | None, requests: int) -> dict[str, Any]:
    return {"amount": (nano or 0) / NANO_PER_UNIT, "requests": requests}


def add_usage(
    thread_id: str, provider: str, model: str, kind: str, *, tokens: dict[str, int], nano: int
) -> dict[str, Any]:
    unknown = set(tokens) - set(TOKEN_COLUMNS)
    if unknown:
        raise ValueError(f"The model reported token types this version cannot store: {', '.join(sorted(unknown))}.")

    counts = {column: int(tokens.get(key, 0)) for key, column in TOKEN_COLUMNS.items()}

    with _begin() as conn:
        conn.execute(
            insert(Usage).values(
                thread_id=thread_id,
                provider=provider,
                model=model,
                kind=kind,
                cost_nano=nano,
                created_at=now_ms(),
                **counts,
            )
        )

        spent, requests = conn.execute(
            select(func.sum(Usage.cost_nano), func.count()).where(Usage.thread_id == thread_id)
        ).one()

    return amounts(spent, requests)


def _summarize(where: Any) -> dict[str, Any]:
    token_sums = [func.coalesce(func.sum(getattr(Usage, column)), 0) for column in TOKEN_COLUMNS.values()]

    with _begin() as conn:
        spent, requests, *tokens = conn.execute(
            select(func.sum(Usage.cost_nano), func.count(), *token_sums).where(where)
        ).one()

        models = conn.execute(
            select(
                Usage.provider,
                Usage.model,
                func.sum(Usage.cost_nano).label("nano"),
                func.count().label("requests"),
            )
            .where(where)
            .group_by(Usage.provider, Usage.model)
            .order_by(desc("nano"))
        ).all()

    return {
        **amounts(spent, requests),
        "tokens": {kind: count for kind, count in zip(TOKEN_COLUMNS, tokens, strict=True) if count},
        "models": [{"model": m.model, "provider": m.provider, **amounts(m.nano, m.requests)} for m in models],
    }


def thread_cost(thread_id: str) -> dict[str, Any]:
    return _summarize(Usage.thread_id == thread_id)


def _daily(since: int, scope: Any) -> dict[str, tuple[int, int]]:
    days: dict[str, tuple[int, int]] = {}
    day = datetime.fromtimestamp(since / 1000).date()
    while day <= datetime.now().date():
        days[day.isoformat()] = (0, 0)
        day += timedelta(days=1)

    label = func.date(Usage.created_at // 1000, "unixepoch", "localtime").label("day")
    with _begin() as conn:
        rows = conn.execute(select(label, func.sum(Usage.cost_nano), func.count()).where(scope).group_by(label)).all()

    return {**days, **{day: (nano or 0, requests) for day, nano, requests in rows}}


def cost_report(since: int, provider: str) -> dict[str, Any]:
    scope = and_(Usage.created_at >= since, Usage.provider == provider)
    threads = (
        select(
            Usage.thread_id,
            Thread.title,
            func.sum(Usage.cost_nano).label("nano"),
            func.count().label("requests"),
        )
        .join(Thread, Thread.id == Usage.thread_id)
        .where(scope)
        .group_by(Usage.thread_id)
        .order_by(desc(func.sum(Usage.cost_nano)))
        .limit(TOP_THREADS)
    )

    with _begin() as conn:
        top = conn.execute(threads).all()

    return {
        **_summarize(scope),
        "days": [{"day": d, **amounts(*spent)} for d, spent in _daily(since, scope).items()],
        "threads": [{"id": t.thread_id, "title": t.title, **amounts(t.nano, t.requests)} for t in top],
    }
