from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, create_engine, desc, event, exists, func, inspect, select, true, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import aliased

from ..errors import EXIT_IN_USE, OvError
from ..paths import agent_dir
from .models import Conversation, Event, Feedback, Pinned, Run, Setting, Settled, Skill, Snoozed, Usage

DB_FILE = "agent.db"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BUSY_TIMEOUT_MS = 10_000

DEFAULT_SETTINGS: dict[str, Any] = {
    "defaultModel": "",
    "fastModel": "",
    "workspace": "",
    "workspaceNotes": "",
    "maxSteps": 80,
    "reasoning": "",
    "followUp": "steer",
    "showTimeSaved": True,
    "expandTools": False,
}

MAX_STEPS_LIMIT = 500
FOLLOW_UPS = ("steer", "queue")
REASONING_LEVELS = ("none", "low", "medium", "high", "xhigh", "max")
NANO_PER_CREDIT = 1_000_000_000
TOP_THREADS = 5
INTERRUPTED_RUN = "Interrupted by a restart."
INTERRUPTED_TOOL = "Interrupted by a restart."
RUN_LIST_LIMIT = 500
ACTIVE = ("queued", "running", "waiting")
RUN_COLUMNS = ("title", "instance", "status", "saved_minutes")

_lock = threading.RLock()
_engine: Engine | None = None
_engine_path = ""


def now_ms() -> int:
    return int(time.time() * 1000)


class DatabaseInUse(OvError):
    exit_code = EXIT_IN_USE

    def __init__(self) -> None:
        super().__init__(
            "This version of ov needs to upgrade the agent database, but another ov agent still has it open. "
            "Stop the other one (Ctrl+C in its window), then run 'ov agent' again."
        )


def _pragmas(dbapi_connection: sqlite3.Connection, _: Any) -> None:
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    cursor.close()


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _backup(path: Path, revision: str | None) -> None:
    target = path.with_name(f"agent.{revision or 'legacy'}.bak.db")
    with sqlite3.connect(path) as source, sqlite3.connect(target) as copy:
        source.backup(copy)


def _begin_transaction(conn: Any) -> None:
    conn.exec_driver_sql("BEGIN")


def _ensure_alone(path: Path) -> None:
    probe = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        if probe.execute("PRAGMA journal_mode = DELETE").fetchone()[0] != "delete":
            raise DatabaseInUse
        probe.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        raise DatabaseInUse from None
    finally:
        probe.close()


def _migrate(engine: Engine, path: Path) -> bool:
    config = _alembic_config()
    head = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        has_data = bool(inspect(conn).get_table_names())
    engine.dispose()
    if current == head:
        return False

    if has_data:
        _ensure_alone(path)
        _backup(path, current)
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    return True


def _new_engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _pragmas)
    event.listen(engine, "begin", _begin_transaction)
    return engine


def _engine_now() -> Engine:
    global _engine, _engine_path
    path = agent_dir() / DB_FILE
    if _engine is not None and _engine_path == str(path):
        return _engine

    close()
    engine = _new_engine(path)
    _migrate(engine, path)
    with engine.begin() as conn:
        _close_orphans(conn)
    _engine, _engine_path = engine, str(path)
    return engine


def migrate() -> bool:
    with _lock:
        close()
        path = agent_dir() / DB_FILE
        engine = _new_engine(path)
        try:
            return _migrate(engine, path)
        finally:
            engine.dispose()


@contextmanager
def _begin() -> Iterator[Connection]:
    with _lock, _engine_now().begin() as conn:
        yield conn


def close() -> None:
    global _engine, _engine_path
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine, _engine_path = None, ""


def _append_next(conn: Connection, run_id: str, data: dict[str, Any]) -> None:
    seq = conn.scalar(select(func.coalesce(func.max(Event.seq), -1) + 1).where(Event.run_id == run_id))
    conn.execute(insert(Event).values(run_id=run_id, seq=seq, ts=now_ms(), data=data))


def _close_orphans(conn: Connection) -> None:
    for run_id in conn.scalars(select(Run.id).where(Run.status.in_(ACTIVE))).all():
        _append_next(conn, run_id, {"type": "status", "status": "error", "error": INTERRUPTED_RUN})

    conn.execute(update(Run).where(Run.status.in_(ACTIVE)).values(status="error"))
    _close_open_tools(conn)


def _field(entity: Any, path: str) -> Any:
    return func.json_extract(entity.data, path)


def _close_open_tools(conn: Connection) -> None:
    later = aliased(Event)
    finished = exists().where(
        later.run_id == Event.run_id,
        later.seq > Event.seq,
        _field(later, "$.type") == "tool",
        _field(later, "$.tool.id") == _field(Event, "$.tool.id"),
        _field(later, "$.tool.status") != "running",
    )
    query = select(Event.run_id, Event.data).where(
        _field(Event, "$.type") == "tool", _field(Event, "$.tool.status") == "running", ~finished
    )
    for run_id, data in conn.execute(query).all():
        tool = {**data["tool"], "status": "error", "output": INTERRUPTED_TOOL}
        _append_next(conn, run_id, {"type": "tool", "tool": tool})


def get_settings() -> dict[str, Any]:
    with _begin() as conn:
        stored = dict(conn.execute(select(Setting.key, Setting.value)).all())
    return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}


def _max_steps(value: Any) -> int:
    try:
        steps = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"maxSteps must be a whole number, got {value!r}.") from None
    return min(max(steps, 1), MAX_STEPS_LIMIT)


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    if "maxSteps" in patch:
        patch = {**patch, "maxSteps": _max_steps(patch["maxSteps"])}
    if patch.get("reasoning") and patch["reasoning"] not in REASONING_LEVELS:
        raise ValueError(f"Unknown reasoning level: {patch['reasoning']}")
    if "followUp" in patch and patch["followUp"] not in FOLLOW_UPS:
        raise ValueError(f"followUp must be one of {', '.join(FOLLOW_UPS)}.")
    if "workspace" in patch:
        from .project import validate_folder

        patch = {**patch, "workspace": validate_folder(str(patch["workspace"]))}

    with _begin() as conn:
        for key, value in patch.items():
            if key not in DEFAULT_SETTINGS:
                continue
            stored = bool(value) if isinstance(DEFAULT_SETTINGS[key], bool) else value
            statement = insert(Setting).values(key=key, value=stored)
            conn.execute(statement.on_conflict_do_update(index_elements=[Setting.key], set_={"value": stored}))
    return get_settings()


def _run_query() -> Any:
    usage_of_run = Usage.run_id == Run.id
    return (
        select(
            *Run.__table__.columns,
            Feedback.rating,
            Settled.ts.label("settled_at"),
            Pinned.ts.label("pinned_at"),
            Snoozed.until.label("snoozed_until"),
            select(func.sum(Usage.nano)).where(usage_of_run).scalar_subquery().label("nano"),
            select(func.count()).where(usage_of_run).scalar_subquery().label("requests"),
        )
        .outerjoin(Feedback, Feedback.run_id == Run.id)
        .outerjoin(Settled, Settled.run_id == Run.id)
        .outerjoin(Pinned, Pinned.run_id == Run.id)
        .outerjoin(Snoozed, Snoozed.run_id == Run.id)
    )


def _summary(row: Any) -> dict[str, Any]:
    summary = {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "model": row.model,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }
    if row.instance:
        summary["instance"] = row.instance
    if row.rating:
        summary["rating"] = row.rating
    if row.settled_at:
        summary["settled"] = True
    if row.pinned_at:
        summary["pinned"] = True
    if row.snoozed_until and row.snoozed_until > now_ms():
        summary["snoozedUntil"] = row.snoozed_until
    if row.requests:
        summary["cost"] = {"credits": row.nano / NANO_PER_CREDIT, "requests": row.requests}
    return summary


def create_run(run_id: str, title: str, model: str, data: dict[str, Any]) -> None:
    now = now_ms()
    values = {"title": title, "instance": data.get("instance"), "status": "queued", "model": model}
    with _begin() as conn:
        conn.execute(insert(Run).values(id=run_id, input=data, created_at=now, updated_at=now, **values))


def update_run(run_id: str, **patch: Any) -> None:
    values = {k: v for k, v in patch.items() if k in RUN_COLUMNS and v is not None}
    with _begin() as conn:
        conn.execute(update(Run).where(Run.id == run_id).values(updated_at=now_ms(), **values))


def list_runs(settled: bool | None = None, limit: int = RUN_LIST_LIMIT) -> list[dict[str, Any]]:
    query = _run_query()
    if settled is not None:
        query = query.where(Settled.run_id.is_not(None) if settled else Settled.run_id.is_(None))
    with _begin() as conn:
        rows = conn.execute(query.order_by(Run.created_at.desc()).limit(limit)).all()
    return [_summary(r) for r in rows]


def _set_flag(table: Any, run_id: str, on: bool, **values: Any) -> None:
    with _begin() as conn:
        if not on:
            conn.execute(table.__table__.delete().where(table.run_id == run_id))
            return
        statement = insert(table).values(run_id=run_id, **values)
        conn.execute(statement.on_conflict_do_update(index_elements=[table.run_id], set_=values))


def set_pinned(run_id: str, pinned: bool) -> None:
    _set_flag(Pinned, run_id, pinned, ts=now_ms())


def set_snoozed(run_id: str, until: int | None) -> None:
    if until is not None and until <= now_ms():
        raise ValueError("Snooze until a time in the future.")
    _set_flag(Snoozed, run_id, until is not None, until=until)


def set_settled(run_id: str, settled: bool) -> None:
    _set_flag(Settled, run_id, settled, ts=now_ms())


def settled_count() -> int:
    with _begin() as conn:
        return int(conn.scalar(select(func.count()).select_from(Settled)) or 0)


def get_run(run_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    with _begin() as conn:
        row = conn.execute(_run_query().where(Run.id == run_id)).first()
    if row is None:
        return None
    return _summary(row), row.input


def saved_totals(since: int) -> dict[str, int]:
    query = (
        select(func.coalesce(func.sum(Run.saved_minutes), 0), func.count())
        .outerjoin(Feedback, Feedback.run_id == Run.id)
        .where(Run.saved_minutes > 0, Run.created_at >= since, func.coalesce(Feedback.rating, "") != "wrong")
    )
    with _begin() as conn:
        minutes, runs = conn.execute(query).one()
    return {"minutes": minutes, "runs": runs}


def append_event(run_id: str, seq: int, data: dict[str, Any]) -> dict[str, Any]:
    ts = now_ms()
    with _begin() as conn:
        conn.execute(insert(Event).values(run_id=run_id, seq=seq, ts=ts, data=data))
    return {"seq": seq, "ts": ts, "event": data}


def load_events(run_id: str, after: int = -1) -> list[dict[str, Any]]:
    query = select(Event.seq, Event.ts, Event.data).where(Event.run_id == run_id, Event.seq > after)
    with _begin() as conn:
        rows = conn.execute(query.order_by(Event.seq)).all()
    return [{"seq": r.seq, "ts": r.ts, "event": r.data} for r in rows]


def save_conversation(key: str, messages: Any) -> None:
    statement = insert(Conversation).values(run_id=key, messages=messages)
    with _begin() as conn:
        conn.execute(statement.on_conflict_do_update(index_elements=[Conversation.run_id], set_={"messages": messages}))


def load_conversation(key: str) -> Any:
    with _begin() as conn:
        return conn.scalar(select(Conversation.messages).where(Conversation.run_id == key))


def save_feedback(run_id: str, rating: str, note: str) -> None:
    values = {"rating": rating, "note": note, "ts": now_ms()}
    statement = insert(Feedback).values(run_id=run_id, **values)
    with _begin() as conn:
        conn.execute(statement.on_conflict_do_update(index_elements=[Feedback.run_id], set_=values))


def get_feedback(run_id: str) -> dict[str, str] | None:
    with _begin() as conn:
        row = conn.execute(select(Feedback.rating, Feedback.note).where(Feedback.run_id == run_id)).first()
    return {"rating": row.rating, "note": row.note} if row else None


def skill_rows() -> dict[str, dict[str, Any]]:
    with _begin() as conn:
        rows = conn.execute(select(*Skill.__table__.columns)).mappings().all()
    return {row["name"]: dict(row) for row in rows}


def put_skill(name: str, **fields: Any) -> None:
    current = skill_rows().get(name, {"enabled": 1})
    merged = {**current, **{k: v for k, v in fields.items() if k != "name"}}
    values = {
        "title": merged.get("title"),
        "description": merged.get("description"),
        "content": merged.get("content"),
        "enabled": 1 if merged["enabled"] else 0,
    }
    statement = insert(Skill).values(name=name, **values)
    with _begin() as conn:
        conn.execute(statement.on_conflict_do_update(index_elements=[Skill.name], set_=values))


def delete_skill(name: str) -> None:
    with _begin() as conn:
        conn.execute(Skill.__table__.delete().where(Skill.name == name))


def _credits(nano: int | None, requests: int) -> dict[str, Any]:
    return {"credits": (nano or 0) / NANO_PER_CREDIT, "requests": requests}


def add_usage(run_id: str, model: str, kind: str, tokens: dict[str, int], nano: int) -> dict[str, Any]:
    with _begin() as conn:
        conn.execute(insert(Usage).values(run_id=run_id, ts=now_ms(), model=model, kind=kind, tokens=tokens, nano=nano))
        total, requests = conn.execute(select(func.sum(Usage.nano), func.count()).where(Usage.run_id == run_id)).one()
    return _credits(total, requests)


def _summarize(where: Any) -> dict[str, Any]:
    each = func.json_each(Usage.tokens).table_valued("key", "value")
    with _begin() as conn:
        total, requests = conn.execute(select(func.sum(Usage.nano), func.count()).where(where)).one()
        tokens = conn.execute(
            select(each.c.key, func.sum(each.c.value))
            .select_from(Usage)
            .join(each, true())
            .where(where)
            .group_by(each.c.key)
        ).all()
        models = conn.execute(
            select(Usage.model, func.sum(Usage.nano).label("nano"), func.count().label("requests"))
            .where(where)
            .group_by(Usage.model)
            .order_by(desc("nano"))
        ).all()
    return {
        **_credits(total, requests),
        "tokens": {kind: count for kind, count in tokens},
        "models": [{"model": m.model, **_credits(m.nano, m.requests)} for m in models],
    }


def run_cost(run_id: str) -> dict[str, Any]:
    return _summarize(Usage.run_id == run_id)


def _daily_nano(since: int) -> dict[str, int]:
    days: dict[str, int] = {}
    day = datetime.fromtimestamp(since / 1000).date()
    while day <= datetime.now().date():
        days[day.isoformat()] = 0
        day += timedelta(days=1)

    label = func.date(Usage.ts // 1000, "unixepoch", "localtime").label("day")
    with _begin() as conn:
        rows = conn.execute(select(label, func.sum(Usage.nano)).where(Usage.ts >= since).group_by(label)).all()
    return {**days, **dict(rows)}


def cost_report(since: int) -> dict[str, Any]:
    threads = (
        select(Usage.run_id, Run.title, func.sum(Usage.nano).label("nano"))
        .join(Run, Run.id == Usage.run_id)
        .where(Usage.ts >= since)
        .group_by(Usage.run_id)
        .order_by(desc("nano"))
        .limit(TOP_THREADS)
    )
    with _begin() as conn:
        top = conn.execute(threads).all()
    return {
        **_summarize(Usage.ts >= since),
        "days": [{"day": d, "credits": nano / NANO_PER_CREDIT} for d, nano in _daily_nano(since).items()],
        "threads": [{"id": t.run_id, "title": t.title, "credits": t.nano / NANO_PER_CREDIT} for t in top],
    }
