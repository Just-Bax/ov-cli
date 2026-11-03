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
from sqlalchemy import (
    Connection,
    Engine,
    and_,
    create_engine,
    delete,
    desc,
    event,
    exists,
    func,
    inspect,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, aliased

from ov.agent.storage.models import (
    Access,
    Attachment,
    Event,
    EventType,
    Message,
    Preference,
    ProviderModel,
    Reasoning,
    Skill,
    SkillSource,
    Thread,
    ThreadStatus,
    Usage,
)
from ov.core.errors import EXIT_IN_USE, OvError
from ov.core.paths import agent_dir

DB_FILE = "agent.db"
FULL_NAME_REQUIRED = "Your full name is required."
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
BUSY_TIMEOUT_MS = 10_000

PREFERENCE_ROW = 1
DEFAULT_MAX_STEPS = 80
MAX_STEPS_LIMIT = 500
PREFERENCE_COLUMNS = {
    "provider": "provider",
    "reasoning": "reasoning",
    "maxSteps": "max_steps",
    "workspace": "workspace",
    "workspaceNotes": "workspace_notes",
    "fullName": "full_name",
    "instructions": "instructions",
    "notify": "notify",
    "tabBadge": "tab_badge",
}
BOOLEAN_PREFERENCES = ("notify", "tabBadge")
TEXT_PREFERENCES = ("workspace", "workspaceNotes", "fullName", "instructions")
MODEL_PREFERENCES = {"defaultModel": "default_model", "fastModel": "fast_model"}
REASONING_LEVELS = tuple(level.value for level in Reasoning)
DEFAULT_PROVIDER = "copilot"
NANO_PER_UNIT = 1_000_000_000
TOP_THREADS = 5
INTERRUPTED_RUN = "Interrupted by a restart."
INTERRUPTED_TOOL = "Interrupted by a restart."
RUN_LIST_LIMIT = 500
ACTIVE = (ThreadStatus.QUEUED, ThreadStatus.RUNNING, ThreadStatus.WAITING)
THREAD_COLUMNS = ("title", "instance", "status", "access")
ATTENTION_OF_STATUS = {ThreadStatus.DONE: "done", ThreadStatus.ERROR: "failed"}
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
_interrupted: list[str] = []


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

    with engine.connect() as conn:
        raw = conn.connection.dbapi_connection
        raw.execute("PRAGMA foreign_keys = OFF")
        try:
            with conn.begin():
                config.attributes["connection"] = conn
                command.upgrade(config, "head")
                _check_foreign_keys(conn)
        finally:
            raw.execute("PRAGMA foreign_keys = ON")

    return True


def _check_foreign_keys(conn: Connection) -> None:
    broken = conn.exec_driver_sql("PRAGMA foreign_key_check").first()
    if broken is not None:
        raise RuntimeError(f"Migration left a broken reference in {broken[0]}.")


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
    orphans = conn.scalars(select(Thread.id).where(Thread.status.in_(ACTIVE))).all()
    for thread_id in orphans:
        _append_next(conn, thread_id, EventType.STATUS, {"status": ThreadStatus.ERROR, "error": INTERRUPTED_RUN})
    conn.execute(update(Thread).where(Thread.status.in_(ACTIVE)).values(status=ThreadStatus.ERROR))
    _close_open_tools(conn)
    _interrupted.extend(orphans)


def take_interrupted() -> list[str]:
    with _lock:
        _engine_now()
        taken = list(_interrupted)
        _interrupted.clear()
    return taken


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
    }

    statement = insert(Preference).values(id=PREFERENCE_ROW, updated_at=now_ms(), **values)
    conn.execute(statement.on_conflict_do_nothing(index_elements=[Preference.id]))


def get_preferences() -> dict[str, Any]:
    with _begin() as conn:
        row = conn.execute(select(Preference).where(Preference.id == PREFERENCE_ROW)).one()

    values = {key: getattr(row, column) for key, column in PREFERENCE_COLUMNS.items()}
    main, fast = provider_models(row.provider)

    return {
        **values,
        "defaultModel": main,
        "fastModel": fast,
        **{key: values[key] or "" for key in (*TEXT_PREFERENCES, "reasoning")},
        **{key: bool(values[key]) for key in BOOLEAN_PREFERENCES},
    }


def _max_steps(value: Any) -> int:
    try:
        steps = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"maxSteps must be a whole number, got {value!r}.") from None
    return min(max(steps, 1), MAX_STEPS_LIMIT)


def provider_models(provider: str) -> tuple[str, str]:
    with _begin() as conn:
        row = conn.execute(select(ProviderModel).where(ProviderModel.provider == provider)).one_or_none()
    if row is None:
        return "", ""
    return row.default_model or "", row.fast_model or ""


def has_provider_models(provider: str) -> bool:
    with _begin() as conn:
        found = conn.execute(select(ProviderModel.provider).where(ProviderModel.provider == provider)).first()
    return found is not None


def _save_models(conn: Any, provider: str, models: dict[str, Any]) -> None:
    values = {MODEL_PREFERENCES[key]: str(value or "").strip() or None for key, value in models.items()}
    statement = insert(ProviderModel).values(provider=provider, updated_at=now_ms(), **values)
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=[ProviderModel.provider], set_={**values, "updated_at": now_ms()}
        )
    )


def _check_preferences(patch: dict[str, Any]) -> None:
    unknown = set(patch) - set(PREFERENCE_COLUMNS) - set(MODEL_PREFERENCES)
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}.")
    if patch.get("reasoning") and patch["reasoning"] not in REASONING_LEVELS:
        raise ValueError(f"Unknown reasoning level: {patch['reasoning']}")
    if "fullName" in patch and not str(patch["fullName"] or "").strip():
        raise ValueError(FULL_NAME_REQUIRED)


def _preference_values(patch: dict[str, Any]) -> dict[str, Any]:
    _check_preferences(patch)

    values = {PREFERENCE_COLUMNS[key]: value for key, value in patch.items()}
    if "maxSteps" in patch:
        values["max_steps"] = _max_steps(patch["maxSteps"])
    for key in BOOLEAN_PREFERENCES:
        if key in patch:
            values[PREFERENCE_COLUMNS[key]] = bool(patch[key])
    if "workspace" in patch:
        from ov.agent.workspace import validate_folder

        values["workspace"] = validate_folder(str(patch["workspace"]))

    for key in (*TEXT_PREFERENCES, "reasoning"):
        if key in patch:
            values[PREFERENCE_COLUMNS[key]] = str(values[PREFERENCE_COLUMNS[key]] or "").strip() or None

    return values


def save_preferences(patch: dict[str, Any]) -> dict[str, Any]:
    models = {key: value for key, value in patch.items() if key in MODEL_PREFERENCES}
    values = _preference_values({key: value for key, value in patch.items() if key not in MODEL_PREFERENCES})
    with _begin() as conn:
        conn.execute(update(Preference).where(Preference.id == PREFERENCE_ROW).values(updated_at=now_ms(), **values))
        if models:
            provider = conn.execute(select(Preference.provider).where(Preference.id == PREFERENCE_ROW)).scalar_one()
            _save_models(conn, provider, models)
    return get_preferences()


def _thread_query() -> Any:
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
    if not _unseen_since(thread, thread.status_at):
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

    if thread.instance:
        summary["instance"] = thread.instance
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
        summary["cost"] = _amounts(nano, requests)

    return summary


def _rows(query: Any) -> list[dict[str, Any]]:
    with _begin() as conn, Session(bind=conn) as session:
        return [_summary(*row) for row in session.execute(query).all()]


def create_thread(
    thread_id: str,
    title: str,
    provider: str,
    model: str,
    *,
    prompt: str,
    instance: str | None,
    access: Access,
) -> dict[str, Any]:
    now = now_ms()
    values = {
        "title": title,
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "instance": instance,
        "access": access,
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
        values["status_at"] = now

    with _begin() as conn:
        conn.execute(update(Thread).where(Thread.id == thread_id).values(updated_at=now, **values))


def list_threads(settled: bool | None = None, limit: int = RUN_LIST_LIMIT) -> list[dict[str, Any]]:
    query = _thread_query()
    if settled is not None:
        query = query.where(Thread.settled_at.is_not(None) if settled else Thread.settled_at.is_(None))
    return _rows(query.order_by(Thread.created_at.desc()).limit(limit))


def get_thread(thread_id: str) -> dict[str, Any] | None:
    found = _rows(_thread_query().where(Thread.id == thread_id))
    return found[0] if found else None


def thread_access(thread_id: str) -> Access:
    with _begin() as conn:
        return Access(conn.scalar(select(Thread.access).where(Thread.id == thread_id)))


def delete_thread(thread_id: str) -> None:
    with _begin() as conn:
        conn.execute(delete(Thread).where(Thread.id == thread_id))


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


def _amounts(nano: int | None, requests: int) -> dict[str, Any]:
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

    return _amounts(spent, requests)


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
        **_amounts(spent, requests),
        "tokens": {kind: count for kind, count in zip(TOKEN_COLUMNS, tokens, strict=True) if count},
        "models": [{"model": m.model, "provider": m.provider, **_amounts(m.nano, m.requests)} for m in models],
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
        "days": [{"day": d, **_amounts(*spent)} for d, spent in _daily(since, scope).items()],
        "threads": [{"id": t.thread_id, "title": t.title, **_amounts(t.nano, t.requests)} for t in top],
    }
