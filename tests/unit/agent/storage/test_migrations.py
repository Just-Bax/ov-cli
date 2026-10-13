from __future__ import annotations

from pathlib import Path

from helpers.fixture_files import read_fixture

from ov.agent import skills
from ov.agent.storage import db, models

LEGACY_ROWS = tuple(read_fixture("legacy_agent_rows.sql").splitlines())


def _legacy_database(home: Path, monkeypatch) -> Path:
    import sqlite3

    from ov.agent.storage.migrations.versions import v0001_baseline as baseline

    monkeypatch.setenv("OV_HOME", str(home))
    path = home / "agent" / "agent.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as legacy:
        for statement in (*baseline.LEGACY_SCHEMA, *LEGACY_ROWS):
            legacy.execute(statement)
    legacy.close()
    return path


def test_a_legacy_database_is_backed_up_and_migrated_to_the_thread_schema(ov_home, monkeypatch):
    import sqlite3

    ov_home = ov_home / "legacy"
    path = _legacy_database(ov_home, monkeypatch)

    (thread,) = db.list_threads()
    assert (thread["title"], thread["settled"], thread["pinned"]) == ("Old", True, True)
    assert db.thread_writes("r1") is True
    assert db.thread_cost("r1")["tokens"] == {"input": 3, "cache_read": 4}
    assert [e["event"]["type"] for e in db.load_events("r1")] == ["user", "message", "access"]
    assert db.load_events("r1")[1]["event"]["text"] == "Hello"
    messages, turns = db.load_messages("r1")
    assert [m["role"] for m in messages] == ["system", "user", "assistant"] and turns == {"u_start": 1}
    assert db.get_preferences()["maxSteps"] == 40
    listed = {s["name"]: s for s in skills.list_skills()}
    assert not listed["ov-cli"]["enabled"] and listed["ov-cli-edited"]["content"] == "mine"
    assert (ov_home / "agent" / "agent.legacy.bak.db").exists()

    with sqlite3.connect(path) as migrated:
        tables = {r[0] for r in migrated.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        attachments = migrated.execute("SELECT thread_id, turn_id, name FROM attachment").fetchall()
    migrated.close()
    assert attachments == [("r1", "u_start", "a.png")]
    assert {"thread", "attachment", "event", "message", "usage", "preference", "skill"} <= tables
    assert not tables & {"run", "runs", "conversation", "settled", "pinned", "snoozed", "feedback", "setting"}


def test_models_match_the_migrations():
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    db.list_threads()
    with db._begin() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), models.Base.metadata)
    assert diffs == []
