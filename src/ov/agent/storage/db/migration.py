from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect

from ov.agent.storage.models import Base
from ov.core.errors import EXIT_IN_USE, OvError

LAST_COMMIT_FOR_OLDER = "e4ab0e9"
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


class DatabaseTooOld(OvError):
    def __init__(self, revision: str | None) -> None:
        super().__init__(
            f"The agent database (revision {revision or 'before migrations'}) is older than this version of ov can "
            f"upgrade. Install ov at commit {LAST_COMMIT_FOR_OLDER}, run 'ov agent --migrate', then update again."
        )


class DatabaseInUse(OvError):
    exit_code = EXIT_IN_USE

    def __init__(self) -> None:
        super().__init__(
            "This version of ov needs to upgrade the agent database, but another ov agent still has it open. "
            "Stop the other one (Ctrl+C in its window), then run 'ov agent' again."
        )


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _backup(path: Path, revision: str) -> None:
    target = path.with_name(f"agent.{revision}.bak.db")
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


def _create_fresh(engine: Engine, config: Config) -> None:
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        config.attributes["connection"] = conn
        command.stamp(config, "head")


def migrate_engine(engine: Engine, path: Path) -> bool:
    config = _alembic_config()
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        has_data = bool(inspect(conn).get_table_names())
    engine.dispose()
    if current == head:
        return False

    if not has_data:
        _create_fresh(engine, config)
        return True

    known = {script.revision for script in scripts.walk_revisions()}
    if current not in known:
        raise DatabaseTooOld(current)

    _ensure_alone(path)
    _backup(path, current)
    _upgrade(engine, config)
    return True


def _upgrade(engine: Engine, config: Config) -> None:
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


def _check_foreign_keys(conn: Connection) -> None:
    broken = conn.exec_driver_sql("PRAGMA foreign_key_check").first()
    if broken is not None:
        raise RuntimeError(f"Migration left a broken reference in {broken[0]}.")
