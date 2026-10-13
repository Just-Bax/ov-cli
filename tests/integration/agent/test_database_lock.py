from __future__ import annotations

import pytest

from ov.agent.storage import db

HOLD_DATABASE = (
    "import sqlite3, time; c = sqlite3.connect(r'{path}'); c.execute('select 1 from runs'); "
    "print('open', flush=True); time.sleep(30)"
)


def test_an_upgrade_waits_while_another_process_has_the_database_open(ov_home, monkeypatch):
    import sqlite3
    import subprocess
    import sys

    from ov.agent.storage.migrations.versions import v0001_baseline as baseline

    ov_home = ov_home / "busy"
    monkeypatch.setenv("OV_HOME", str(ov_home))
    path = ov_home / "agent" / "agent.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as legacy:
        legacy.execute("PRAGMA journal_mode = WAL")
        for statement in baseline.LEGACY_SCHEMA:
            legacy.execute(statement)
    legacy.close()
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_DATABASE.format(path=path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout.readline().strip() == "open"
        with pytest.raises(db.DatabaseInUse):
            db.migrate()
    finally:
        holder.kill()
        holder.wait()

    assert db.migrate() is True
    assert db.migrate() is False
