from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from helpers.fixture_files import read_fixture

from ov.agent.storage import db, models

OLDEST_SCHEMA = tuple(s for s in read_fixture("agent_0020.sql").split(";\n") if s.strip())


def _database(home: Path, monkeypatch, statements: tuple[str, ...]) -> Path:
    monkeypatch.setenv("OV_HOME", str(home))
    path = home / "agent" / "agent.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as old:
        for statement in statements:
            old.execute(statement)
    old.close()
    return path


def _schema(path: Path) -> dict[tuple[str, str], str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    conn.close()
    return {(kind, name): re.sub(r"\s+", " ", sql.replace('"', "")).strip() for kind, name, sql in rows}


def test_a_new_database_is_created_from_the_models_at_head(ov_home, monkeypatch):
    monkeypatch.setenv("OV_HOME", str(ov_home / "fresh"))
    assert db.migrate() is True
    assert db.migrate() is False
    with sqlite3.connect(ov_home / "fresh" / "agent" / "agent.db") as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("0023",)]
    conn.close()


def test_the_oldest_supported_database_migrates_to_exactly_the_model_schema(ov_home, monkeypatch):
    migrated = _database(ov_home / "old", monkeypatch, OLDEST_SCHEMA)
    db.migrate()
    db.close()

    monkeypatch.setenv("OV_HOME", str(ov_home / "fresh"))
    db.migrate()
    db.close()

    assert _schema(migrated) == _schema(ov_home / "fresh" / "agent" / "agent.db")
    assert (ov_home / "old" / "agent" / "agent.0020.bak.db").exists()


def test_migrating_renames_events_and_usage_and_links_continued_threads(ov_home, monkeypatch):
    _database(ov_home / "old", monkeypatch, OLDEST_SCHEMA)

    assert [e["event"]["type"] for e in db.load_events("r1")] == [
        "user_message",
        "agent_message",
        "queue_add",
        "queue_order",
        "queue_remove",
    ]
    assert [e["event"] for e in db.load_events("r2")] == [{"type": "meta", "title": "Source (continued)"}]

    (child,) = [t for t in db.list_threads() if t["id"] == "r2"]
    assert (child["parentId"], child["origin"]) == ("r1", "branch")
    assert db.thread_cost("r1")["tokens"] == {"input": 4, "cache_read": 4, "output": 2}
    assert db.get_preferences()["maxSteps"] == 40
    assert db.get_preferences()["compactBranches"] is False
    assert db.get_preferences()["boost"] is False

    with db._begin() as conn:
        kinds = sorted(conn.exec_driver_sql("SELECT kind FROM usage").scalars().all())
        tables = set(conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'").scalars().all())
    assert kinds == ["agent", "title"]
    assert "attachment" not in tables and "finding" not in tables


def test_a_database_older_than_the_oldest_supported_one_is_refused(ov_home, monkeypatch):
    _database(ov_home / "older", monkeypatch, ("CREATE TABLE runs (id TEXT PRIMARY KEY)",))
    with pytest.raises(db.DatabaseTooOld, match="before migrations"):
        db.migrate()


def test_models_match_the_migrations():
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    db.list_threads()
    with db._begin() as conn:
        context = MigrationContext.configure(conn, opts={"compare_server_default": True, "compare_type": True})
        diffs = compare_metadata(context, models.Base.metadata)
    assert diffs == []
