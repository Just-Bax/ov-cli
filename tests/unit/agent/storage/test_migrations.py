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
    assert db.thread_access("r1") == models.Access.ASK
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


def test_old_case_reply_usage_is_kept_as_naming_cost(ov_home, monkeypatch):
    from alembic import command

    home = ov_home / "reply"
    monkeypatch.setenv("OV_HOME", str(home))
    path = home / "agent" / "agent.db"
    path.parent.mkdir(parents=True)
    engine = db._new_engine(path)
    config = db._alembic_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0006")
        conn.exec_driver_sql(
            "INSERT INTO thread (id, title, status, model, prompt, allow_write, created_at, updated_at) "
            "VALUES ('r1', 'Old', 'done', 'm', '', 0, 1, 1)"
        )
        conn.exec_driver_sql(
            "INSERT INTO usage (thread_id, model, kind, input_tokens, cached_tokens, cache_write_tokens, "
            "output_tokens, cost_nano, created_at) VALUES ('r1', 'm', 'reply', 1, 0, 0, 2, 7, 1)"
        )

    engine.dispose()

    assert db.migrate() is True
    with db._begin() as conn:
        rows = conn.exec_driver_sql("SELECT kind, cost_nano FROM usage").all()
    assert [tuple(r) for r in rows] == [("naming", 7)]


def test_write_access_becomes_an_access_mode_and_keeps_thread_events(ov_home, monkeypatch):
    from alembic import command

    home = ov_home / "access"
    monkeypatch.setenv("OV_HOME", str(home))
    path = home / "agent" / "agent.db"
    path.parent.mkdir(parents=True)
    engine = db._new_engine(path)
    config = db._alembic_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0009")
        for thread_id, allowed in (("rw", 1), ("rr", 0)):
            conn.exec_driver_sql(
                "INSERT INTO thread (id, title, status, model, prompt, allow_write, created_at, updated_at) "
                f"VALUES ('{thread_id}', 'T', 'done', 'm', '', {allowed}, 1, 1)"
            )
        conn.exec_driver_sql(
            "INSERT INTO event (thread_id, position, type, data, created_at) "
            """VALUES ('rw', 0, 'access', '{"type": "access", "write": true}', 1)"""
        )

    engine.dispose()

    assert db.migrate() is True
    assert db.thread_access("rw") == models.Access.ASK
    assert db.thread_access("rr") == models.Access.READ
    assert [e["event"] for e in db.load_events("rw")] == [{"type": "access", "access": "ask"}]


def test_old_questions_become_asks_and_approvals():
    from ov.agent.storage.migrations.versions.v0011_question_items import _converted

    ask = _converted({"id": "q1", "question": "Which?", "options": ["a", "b"], "multiple": False, "answer": "b"})
    assert ask == {
        "id": "q1",
        "kind": "ask",
        "items": [{"header": "", "question": "Which?", "options": [{"label": "a"}, {"label": "b"}], "multiple": False}],
        "answers": ["b"],
    }

    detail = "rm x\n\nAuto mode asks because this looks risky: deletes"
    approval = _converted({"id": "q2", "question": "Run?", "detail": detail, "toolId": "c1"})
    assert approval == {
        "id": "q2",
        "kind": "approval",
        "question": "Run?",
        "detail": "rm x",
        "reason": "deletes",
        "toolId": "c1",
    }

    stopped = _converted({"id": "q3", "question": "Which?", "options": [], "answer": "(not answered: the run stopped)"})
    assert stopped["stopped"] is True and "answers" not in stopped


def test_claude_sessions_become_provider_sessions_and_providers_are_open(ov_home, monkeypatch):
    from alembic import command

    home = ov_home / "sessions"
    monkeypatch.setenv("OV_HOME", str(home))
    path = home / "agent" / "agent.db"
    path.parent.mkdir(parents=True)
    engine = db._new_engine(path)
    config = db._alembic_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0017")
        conn.exec_driver_sql(
            "INSERT INTO thread (id, title, instance, status, provider, model, prompt, access, created_at, updated_at) "
            "VALUES ('rc', 'T', NULL, 'done', 'claude', 'opus', '', 'read', 1, 1)"
        )
        anchor = '{"claude": {"session": "s1", "turn": "u_start", "prompt": "p1", "spent": 0.5}}'
        conn.exec_driver_sql(
            f"INSERT INTO event (thread_id, position, type, data, created_at) VALUES ('rc', 0, 'meta', '{anchor}', 1)"
        )

    engine.dispose()

    assert db.migrate() is True
    [event] = db.load_events("rc")
    assert event["event"] == {
        "type": "meta",
        "session": {"id": "s1", "turn": "u_start", "prompt": "p1", "spent": 0.5},
    }
    db.create_thread("rn", "New", "some-new-provider", "m", prompt="", instance=None, access=models.Access.READ)
    assert db.get_preferences()["instructions"] == ""
