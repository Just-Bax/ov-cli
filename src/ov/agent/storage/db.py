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
from sqlalchemy import Connection, Engine, create_engine, delete, desc, event, exists, func, inspect, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import aliased

from ov.agent.storage.models import (
    Attachment,
    Event,
    EventType,
    FollowUp,
    Message,
    Preference,
    Reasoning,
    Skill,
    SkillSource,
    Thread,
    ThreadStatus,
    Usage,
    Walkthrough,
    WalkthroughRun,
)
from ov.core.errors import EXIT_IN_USE, OvError
from ov.core.paths import agent_dir

DB_FILE = "agent.db"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BUSY_TIMEOUT_MS = 10_000

PREFERENCE_ROW = 1
DEFAULT_MAX_STEPS = 80
MAX_STEPS_LIMIT = 500
PREFERENCE_COLUMNS = {
    "defaultModel": "default_model",
    "fastModel": "fast_model",
    "reasoning": "reasoning",
    "maxSteps": "max_steps",
    "followUp": "follow_up",
    "workspace": "workspace",
    "workspaceNotes": "workspace_notes",
    "expandTools": "expand_tools",
}
TEXT_PREFERENCES = ("defaultModel", "fastModel", "workspace", "workspaceNotes")
REASONING_LEVELS = tuple(level.value for level in Reasoning)
FOLLOW_UPS = tuple(mode.value for mode in FollowUp)
NANO_PER_CREDIT = 1_000_000_000
TOP_THREADS = 5
INTERRUPTED_RUN = "Interrupted by a restart."
INTERRUPTED_TOOL = "Interrupted by a restart."
RUN_LIST_LIMIT = 500
ACTIVE = (ThreadStatus.QUEUED, ThreadStatus.RUNNING, ThreadStatus.WAITING)
THREAD_COLUMNS = ("title", "instance", "status", "allow_write")
TOKEN_COLUMNS = {
    "input": "input_tokens",
    "cache_read": "cached_tokens",
    "cache_write": "cache_write_tokens",
    "output": "output_tokens",
}
SKILL_FIELDS = ("title", "description", "content", "enabled")

_lock = threading.RLock()
_engine: Engine | None = None
_engine_path = ""


class DatabaseInUse(OvError):
    exit_code = EXIT_IN_USE

    def __init__(self) -> None:
        super().__init__(
            "This version of ov needs to upgrade the agent database, but another ov agent still has it open. "
            "Stop the other one (Ctrl+C in its window), then run 'ov agent' again."
        )


def now_ms() -> int:
    return int(time.time() * 1000)


def _pragmas(dbapi_connection: sqlite3.Connection, _: Any) -> None:
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    cursor.close()


def _begin_transaction(conn: Any) -> None:
    conn.exec_driver_sql("BEGIN")


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _backup(path: Path, revision: str | None) -> None:
    target = path.with_name(f"agent.{revision or 'legacy'}.bak.db")
    with sqlite3.connect(path) as source, sqlite3.connect(target) as copy:
        source.backup(copy)


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
        conn.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
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
        _ensure_preferences(conn)
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


def _append_next(conn: Connection, thread_id: str, kind: EventType, data: dict[str, Any]) -> None:
    position = conn.scalar(select(func.coalesce(func.max(Event.position), -1) + 1).where(Event.thread_id == thread_id))
    conn.execute(
        insert(Event).values(thread_id=thread_id, position=position, type=kind, data=data, created_at=now_ms())
    )


def _close_orphans(conn: Connection) -> None:
    for thread_id in conn.scalars(select(Thread.id).where(Thread.status.in_(ACTIVE))).all():
        _append_next(conn, thread_id, EventType.STATUS, {"status": ThreadStatus.ERROR, "error": INTERRUPTED_RUN})
    conn.execute(update(Thread).where(Thread.status.in_(ACTIVE)).values(status=ThreadStatus.ERROR))
    _close_open_tools(conn)


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
    values = {"max_steps": DEFAULT_MAX_STEPS, "follow_up": FollowUp.STEER, "expand_tools": False}
    statement = insert(Preference).values(id=PREFERENCE_ROW, updated_at=now_ms(), **values)
    conn.execute(statement.on_conflict_do_nothing(index_elements=[Preference.id]))


def get_preferences() -> dict[str, Any]:
    with _begin() as conn:
        row = conn.execute(select(Preference).where(Preference.id == PREFERENCE_ROW)).one()
    values = {key: getattr(row, column) for key, column in PREFERENCE_COLUMNS.items()}
    return {
        **values,
        **{key: values[key] or "" for key in (*TEXT_PREFERENCES, "reasoning")},
        "expandTools": bool(values["expandTools"]),
    }


def _max_steps(value: Any) -> int:
    try:
        steps = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"maxSteps must be a whole number, got {value!r}.") from None
    return min(max(steps, 1), MAX_STEPS_LIMIT)


def _check_preferences(patch: dict[str, Any]) -> None:
    unknown = set(patch) - set(PREFERENCE_COLUMNS)
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}.")
    if patch.get("reasoning") and patch["reasoning"] not in REASONING_LEVELS:
        raise ValueError(f"Unknown reasoning level: {patch['reasoning']}")
    if "followUp" in patch and patch["followUp"] not in FOLLOW_UPS:
        raise ValueError(f"followUp must be one of {', '.join(FOLLOW_UPS)}.")


def _preference_values(patch: dict[str, Any]) -> dict[str, Any]:
    _check_preferences(patch)
    values = {PREFERENCE_COLUMNS[key]: value for key, value in patch.items()}
    if "maxSteps" in patch:
        values["max_steps"] = _max_steps(patch["maxSteps"])
    if "expandTools" in patch:
        values["expand_tools"] = bool(patch["expandTools"])
    if "workspace" in patch:
        from ov.agent.workspace import validate_folder

        values["workspace"] = validate_folder(str(patch["workspace"]))
    for key in (*TEXT_PREFERENCES, "reasoning"):
        if key in patch:
            values[PREFERENCE_COLUMNS[key]] = str(values[PREFERENCE_COLUMNS[key]] or "").strip() or None
    return values


def save_preferences(patch: dict[str, Any]) -> dict[str, Any]:
    values = _preference_values(patch)
    with _begin() as conn:
        conn.execute(update(Preference).where(Preference.id == PREFERENCE_ROW).values(updated_at=now_ms(), **values))
    return get_preferences()


def _thread_query() -> Any:
    usage_of_thread = Usage.thread_id == Thread.id
    return select(
        Thread,
        select(func.sum(Usage.cost_nano)).where(usage_of_thread).scalar_subquery().label("nano"),
        select(func.count()).where(usage_of_thread).scalar_subquery().label("requests"),
    )


def _summary(thread: Thread, nano: int | None, requests: int) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": thread.id,
        "title": thread.title,
        "status": thread.status,
        "model": thread.model,
        "createdAt": thread.created_at,
        "updatedAt": thread.updated_at,
    }
    if thread.instance:
        summary["instance"] = thread.instance
    if thread.settled_at:
        summary["settled"] = True
    if thread.pinned_at:
        summary["pinned"] = True
    if thread.snoozed_until and thread.snoozed_until > now_ms():
        summary["snoozedUntil"] = thread.snoozed_until
    if requests:
        summary["cost"] = _credits(nano, requests)
    return summary


def _rows(query: Any) -> list[dict[str, Any]]:
    from sqlalchemy.orm import Session

    with _begin() as conn, Session(bind=conn) as session:
        return [_summary(thread, nano, requests) for thread, nano, requests in session.execute(query).all()]


def create_thread(
    thread_id: str, title: str, model: str, *, prompt: str, instance: str | None, allow_write: bool
) -> dict[str, Any]:
    now = now_ms()
    values = {"title": title, "model": model, "prompt": prompt, "instance": instance, "allow_write": allow_write}
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
    with _begin() as conn:
        conn.execute(update(Thread).where(Thread.id == thread_id).values(updated_at=now_ms(), **values))


def list_threads(settled: bool | None = None, limit: int = RUN_LIST_LIMIT) -> list[dict[str, Any]]:
    query = _thread_query()
    if settled is not None:
        query = query.where(Thread.settled_at.is_not(None) if settled else Thread.settled_at.is_(None))
    return _rows(query.order_by(Thread.created_at.desc()).limit(limit))


def get_thread(thread_id: str) -> dict[str, Any] | None:
    found = _rows(_thread_query().where(Thread.id == thread_id))
    return found[0] if found else None


def thread_writes(thread_id: str) -> bool:
    with _begin() as conn:
        return bool(conn.scalar(select(Thread.allow_write).where(Thread.id == thread_id)))


def delete_thread(thread_id: str) -> None:
    with _begin() as conn:
        conn.execute(delete(Thread).where(Thread.id == thread_id))


def set_pinned(thread_id: str, pinned: bool) -> None:
    _set_thread(thread_id, pinned_at=now_ms() if pinned else None)


def set_snoozed(thread_id: str, until: int | None) -> None:
    if until is not None and until <= now_ms():
        raise ValueError("Snooze until a time in the future.")
    _set_thread(thread_id, snoozed_until=until)


def set_settled(thread_id: str, settled: bool) -> None:
    _set_thread(thread_id, settled_at=now_ms() if settled else None)


def _set_thread(thread_id: str, **values: Any) -> None:
    with _begin() as conn:
        conn.execute(update(Thread).where(Thread.id == thread_id).values(**values))


def settled_count() -> int:
    with _begin() as conn:
        return int(conn.scalar(select(func.count()).where(Thread.settled_at.is_not(None))) or 0)


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
    from sqlalchemy.orm import Session

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


def add_attachments(thread_id: str, turn_id: str, names: list[str]) -> None:
    if not names:
        return
    created = now_ms()
    rows = [{"thread_id": thread_id, "turn_id": turn_id, "name": name, "created_at": created} for name in names]
    with _begin() as conn:
        conn.execute(insert(Attachment), rows)


def skill_rows() -> dict[str, dict[str, Any]]:
    with _begin() as conn:
        rows = conn.execute(select(*Skill.__table__.columns).order_by(Skill.name)).mappings().all()
    return {row["name"]: {**row, "enabled": bool(row["enabled"])} for row in rows}


def sync_bundled(skills: list[dict[str, str]]) -> None:
    now = now_ms()
    names = [skill["name"] for skill in skills]
    with _begin() as conn:
        conn.execute(delete(Skill).where(Skill.source == SkillSource.BUNDLED, Skill.name.not_in(names)))
        for skill in skills:
            text = {k: skill[k] for k in ("title", "description", "content")}
            statement = insert(Skill).values(
                name=skill["name"], source=SkillSource.BUNDLED, enabled=True, created_at=now, updated_at=now, **text
            )
            conn.execute(
                statement.on_conflict_do_update(
                    index_elements=[Skill.name], set_=text, where=Skill.source == SkillSource.BUNDLED
                )
            )


def add_skill(name: str, title: str, description: str, content: str) -> None:
    now = now_ms()
    values = {"title": title, "description": description, "content": content}
    with _begin() as conn:
        conn.execute(
            insert(Skill).values(
                name=name, source=SkillSource.CUSTOM, enabled=True, created_at=now, updated_at=now, **values
            )
        )


def update_skill(name: str, **fields: Any) -> None:
    unknown = set(fields) - set(SKILL_FIELDS)
    if unknown:
        raise ValueError(f"Skills have no {', '.join(sorted(unknown))}.")
    with _begin() as conn:
        conn.execute(update(Skill).where(Skill.name == name).values(updated_at=now_ms(), **fields))


def delete_skill(name: str) -> None:
    with _begin() as conn:
        conn.execute(delete(Skill).where(Skill.name == name, Skill.source == SkillSource.CUSTOM))


def _credits(nano: int | None, requests: int) -> dict[str, Any]:
    return {"credits": (nano or 0) / NANO_PER_CREDIT, "requests": requests}


def add_usage(thread_id: str, model: str, kind: str, tokens: dict[str, int], nano: int) -> dict[str, Any]:
    unknown = set(tokens) - set(TOKEN_COLUMNS)
    if unknown:
        raise ValueError(f"Copilot reported token types this version cannot store: {', '.join(sorted(unknown))}.")
    counts = {column: int(tokens.get(key, 0)) for key, column in TOKEN_COLUMNS.items()}
    with _begin() as conn:
        conn.execute(
            insert(Usage).values(
                thread_id=thread_id, model=model, kind=kind, cost_nano=nano, created_at=now_ms(), **counts
            )
        )
        total, requests = conn.execute(
            select(func.sum(Usage.cost_nano), func.count()).where(Usage.thread_id == thread_id)
        ).one()
    return _credits(total, requests)


def _summarize(where: Any) -> dict[str, Any]:
    token_sums = [func.coalesce(func.sum(getattr(Usage, column)), 0) for column in TOKEN_COLUMNS.values()]
    with _begin() as conn:
        total, requests, *tokens = conn.execute(
            select(func.sum(Usage.cost_nano), func.count(), *token_sums).where(where)
        ).one()
        models = conn.execute(
            select(Usage.model, func.sum(Usage.cost_nano).label("nano"), func.count().label("requests"))
            .where(where)
            .group_by(Usage.model)
            .order_by(desc("nano"))
        ).all()
    return {
        **_credits(total, requests),
        "tokens": {kind: count for kind, count in zip(TOKEN_COLUMNS, tokens, strict=True) if count},
        "models": [{"model": m.model, **_credits(m.nano, m.requests)} for m in models],
    }


def thread_cost(thread_id: str) -> dict[str, Any]:
    return _summarize(Usage.thread_id == thread_id)


def _daily_nano(since: int) -> dict[str, int]:
    days: dict[str, int] = {}
    day = datetime.fromtimestamp(since / 1000).date()
    while day <= datetime.now().date():
        days[day.isoformat()] = 0
        day += timedelta(days=1)

    label = func.date(Usage.created_at // 1000, "unixepoch", "localtime").label("day")
    with _begin() as conn:
        rows = conn.execute(
            select(label, func.sum(Usage.cost_nano)).where(Usage.created_at >= since).group_by(label)
        ).all()
    return {**days, **dict(rows)}


def cost_report(since: int) -> dict[str, Any]:
    threads = (
        select(Usage.thread_id, Thread.title, func.sum(Usage.cost_nano).label("nano"))
        .join(Thread, Thread.id == Usage.thread_id)
        .where(Usage.created_at >= since)
        .group_by(Usage.thread_id)
        .order_by(desc("nano"))
        .limit(TOP_THREADS)
    )
    with _begin() as conn:
        top = conn.execute(threads).all()
    return {
        **_summarize(Usage.created_at >= since),
        "days": [{"day": d, "credits": nano / NANO_PER_CREDIT} for d, nano in _daily_nano(since).items()],
        "threads": [{"id": t.thread_id, "title": t.title, "credits": t.nano / NANO_PER_CREDIT} for t in top],
    }


def _walkthrough(row: Walkthrough) -> dict[str, Any]:
    return {
        "id": row.id,
        "instance": row.instance,
        "title": row.title,
        "goal": row.goal,
        "steps": row.steps,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def create_walkthrough(walkthrough_id: str, instance: str, title: str, goal: str, steps: list[str]) -> dict[str, Any]:
    now = now_ms()
    with _begin() as conn:
        conn.execute(
            insert(Walkthrough).values(
                id=walkthrough_id,
                instance=instance,
                title=title,
                goal=goal,
                steps=steps,
                created_at=now,
                updated_at=now,
            )
        )
    found = get_walkthrough(walkthrough_id)
    if found is None:
        raise ValueError(f"Walkthrough {walkthrough_id} was not saved.")
    return found


def update_walkthrough(walkthrough_id: str, **patch: Any) -> dict[str, Any] | None:
    allowed = {k: v for k, v in patch.items() if k in ("title", "goal", "steps", "instance") and v is not None}
    with _begin() as conn:
        conn.execute(update(Walkthrough).where(Walkthrough.id == walkthrough_id).values(updated_at=now_ms(), **allowed))
    return get_walkthrough(walkthrough_id)


def list_walkthroughs() -> list[dict[str, Any]]:
    from sqlalchemy.orm import Session

    with _begin() as conn, Session(bind=conn) as session:
        rows = session.scalars(select(Walkthrough).order_by(Walkthrough.created_at.desc())).all()
        return [_walkthrough(r) for r in rows]


def get_walkthrough(walkthrough_id: str) -> dict[str, Any] | None:
    from sqlalchemy.orm import Session

    with _begin() as conn, Session(bind=conn) as session:
        row = session.scalar(select(Walkthrough).where(Walkthrough.id == walkthrough_id))
        return _walkthrough(row) if row else None


def delete_walkthrough(walkthrough_id: str) -> None:
    with _begin() as conn:
        conn.execute(delete(Walkthrough).where(Walkthrough.id == walkthrough_id))


def _walk_run(row: WalkthroughRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "walkthroughId": row.walkthrough_id,
        "instance": row.instance,
        "title": row.title,
        "goal": row.goal,
        "model": row.model,
        "status": row.status,
        "steps": row.steps,
        "createdAt": row.created_at,
        "finishedAt": row.finished_at,
    }


def create_walk_run(
    run_id: str,
    walkthrough_id: str | None,
    *,
    instance: str,
    title: str,
    goal: str,
    model: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    with _begin() as conn:
        conn.execute(
            insert(WalkthroughRun).values(
                id=run_id,
                walkthrough_id=walkthrough_id,
                instance=instance,
                title=title,
                goal=goal,
                model=model,
                status="pending",
                steps=steps,
                created_at=now_ms(),
                finished_at=None,
            )
        )
    found = get_walk_run(run_id)
    if found is None:
        raise ValueError(f"Walkthrough run {run_id} was not saved.")
    return found


def save_walk_run(run_id: str, status: str, steps: list[dict[str, Any]], finished: bool) -> None:
    values: dict[str, Any] = {"status": status, "steps": steps}
    if finished:
        values["finished_at"] = now_ms()
    with _begin() as conn:
        conn.execute(update(WalkthroughRun).where(WalkthroughRun.id == run_id).values(**values))


def list_walk_runs(walkthrough_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    from sqlalchemy.orm import Session

    query = select(WalkthroughRun).order_by(WalkthroughRun.created_at.desc()).limit(limit)
    if walkthrough_id is not None:
        query = query.where(WalkthroughRun.walkthrough_id == walkthrough_id)
    with _begin() as conn, Session(bind=conn) as session:
        return [_walk_run(r) for r in session.scalars(query).all()]


def get_walk_run(run_id: str) -> dict[str, Any] | None:
    from sqlalchemy.orm import Session

    with _begin() as conn, Session(bind=conn) as session:
        row = session.scalar(select(WalkthroughRun).where(WalkthroughRun.id == run_id))
        return _walk_run(row) if row else None


def delete_walk_run(run_id: str) -> None:
    with _begin() as conn:
        conn.execute(delete(WalkthroughRun).where(WalkthroughRun.id == run_id))
