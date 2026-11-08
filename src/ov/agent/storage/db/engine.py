from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event

from ov.agent.storage.db.migration import migrate_engine
from ov.agent.storage.db.startup import interrupted, prepare
from ov.core.paths import agent_dir

DB_FILE = "agent.db"
BUSY_TIMEOUT_MS = 10_000

_lock = threading.RLock()
_engine: Engine | None = None
_engine_path = ""


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
    migrate_engine(engine, path)

    with engine.begin() as conn:
        prepare(conn)

    _engine, _engine_path = engine, str(path)
    return engine


def migrate() -> bool:
    with _lock:
        close()
        path = agent_dir() / DB_FILE
        engine = _new_engine(path)
        try:
            return migrate_engine(engine, path)
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


def take_interrupted() -> list[str]:
    with _lock:
        _engine_now()
        taken = list(interrupted)
        interrupted.clear()
    return taken
