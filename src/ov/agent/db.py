from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from ..paths import agent_dir

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  instance TEXT,
  status TEXT NOT NULL,
  model TEXT NOT NULL,
  input TEXT NOT NULL,
  saved_minutes INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS conversation (run_id TEXT PRIMARY KEY, messages TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (
  run_id TEXT PRIMARY KEY,
  rating TEXT NOT NULL,
  note TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
  name TEXT PRIMARY KEY,
  title TEXT,
  description TEXT,
  content TEXT,
  enabled INTEGER NOT NULL DEFAULT 1
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "defaultModel": "",
    "fastModel": "",
    "workspace": "",
    "workspaceNotes": "",
    "maxSteps": 80,
    "notify": False,
    "showTimeSaved": True,
    "expandTools": False,
}

MAX_STEPS_LIMIT = 500
RUN_LIST_LIMIT = 200
ACTIVE = ("queued", "running", "waiting")

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_conn_path = ""


def now_ms() -> int:
    return int(time.time() * 1000)


def _db() -> sqlite3.Connection:
    global _conn, _conn_path
    path = str(agent_dir() / "agent.db")
    if _conn is not None and _conn_path == path:
        return _conn

    if _conn is not None:
        _conn.close()
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA synchronous = NORMAL")
    _close_orphans(conn)
    _conn, _conn_path = conn, path
    return conn


def _close_orphans(conn: sqlite3.Connection) -> None:
    marks = ",".join("?" * len(ACTIVE))
    orphans = conn.execute(f"SELECT id FROM runs WHERE status IN ({marks})", ACTIVE).fetchall()
    event = json.dumps({"type": "status", "status": "error", "error": "Interrupted by a restart."})
    for (run_id,) in orphans:
        conn.execute(
            "INSERT INTO events (run_id, seq, ts, data) "
            "SELECT ?, COALESCE(MAX(seq), -1) + 1, ?, ? FROM events WHERE run_id = ?",
            (run_id, now_ms(), event, run_id),
        )

    conn.execute(f"UPDATE runs SET status = 'error' WHERE status IN ({marks})", ACTIVE)


def _all(sql: str, *args: Any) -> list[sqlite3.Row]:
    with _lock:
        return _db().execute(sql, args).fetchall()


def _one(sql: str, *args: Any) -> sqlite3.Row | None:
    with _lock:
        return _db().execute(sql, args).fetchone()


def _run(sql: str, *args: Any) -> None:
    with _lock:
        _db().execute(sql, args)


def close() -> None:
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn, _conn_path = None, ""


def get_settings() -> dict[str, Any]:
    stored = {row["key"]: json.loads(row["value"]) for row in _all("SELECT * FROM settings")}
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
    if "workspace" in patch:
        from .project import validate_folder

        patch = {**patch, "workspace": validate_folder(str(patch["workspace"]))}

    for key, value in patch.items():
        if key not in DEFAULT_SETTINGS:
            continue
        stored = bool(value) if isinstance(DEFAULT_SETTINGS[key], bool) else value
        _run(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            key,
            json.dumps(stored),
        )
    return get_settings()


RUN_SELECT = "SELECT r.*, f.rating FROM runs r LEFT JOIN feedback f ON f.run_id = r.id"


def _summary(row: sqlite3.Row) -> dict[str, Any]:
    summary = {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "model": row["model"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    if row["instance"]:
        summary["instance"] = row["instance"]
    if row["rating"]:
        summary["rating"] = row["rating"]
    return summary


def create_run(run_id: str, title: str, model: str, data: dict[str, Any]) -> None:
    now = now_ms()
    _run(
        "INSERT INTO runs (id, title, instance, status, model, input, created_at, updated_at) "
        "VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)",
        run_id,
        title,
        data.get("instance"),
        model,
        json.dumps(data),
        now,
        now,
    )


def update_run(run_id: str, **patch: Any) -> None:
    columns = {"title", "instance", "status", "saved_minutes"}
    sets = ["updated_at = ?"]
    values: list[Any] = [now_ms()]
    for key, value in patch.items():
        if key in columns and value is not None:
            sets.append(f"{key} = ?")
            values.append(value)
    _run(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", *values, run_id)


def list_runs(limit: int = RUN_LIST_LIMIT) -> list[dict[str, Any]]:
    rows = _all(f"{RUN_SELECT} ORDER BY r.created_at DESC LIMIT ?", limit)
    return [_summary(r) for r in rows]


def get_run(run_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    row = _one(f"{RUN_SELECT} WHERE r.id = ?", run_id)
    if row is None:
        return None
    return _summary(row), json.loads(row["input"])


def delete_run(run_id: str) -> None:
    for table in ("events", "conversation", "feedback"):
        _run(f"DELETE FROM {table} WHERE run_id = ?", run_id)
    _run("DELETE FROM conversation WHERE run_id = ?", f"{run_id}#turns")
    _run("DELETE FROM runs WHERE id = ?", run_id)


def run_ids_for(instance: str) -> list[str]:
    return [row["id"] for row in _all("SELECT id FROM runs WHERE instance = ?", instance)]


def run_ids_outside(instances: set[str]) -> list[str]:
    rows = _all("SELECT id, instance FROM runs WHERE instance IS NOT NULL AND instance != ''")
    return [row["id"] for row in rows if row["instance"] not in instances]


def saved_totals(since: int) -> dict[str, int]:
    (row,) = _all(
        "SELECT COALESCE(SUM(r.saved_minutes), 0) AS minutes, COUNT(*) AS runs "
        "FROM runs r LEFT JOIN feedback f ON f.run_id = r.id "
        "WHERE r.saved_minutes > 0 AND r.created_at >= ? AND COALESCE(f.rating, '') <> 'wrong'",
        since,
    )
    return {"minutes": row["minutes"], "runs": row["runs"]}


def append_event(run_id: str, seq: int, event: dict[str, Any]) -> dict[str, Any]:
    ts = now_ms()
    _run(
        "INSERT INTO events (run_id, seq, ts, data) VALUES (?, ?, ?, ?)",
        run_id,
        seq,
        ts,
        json.dumps(event),
    )
    return {"seq": seq, "ts": ts, "event": event}


def load_events(run_id: str, after: int = -1) -> list[dict[str, Any]]:
    rows = _all("SELECT seq, ts, data FROM events WHERE run_id = ? AND seq > ? ORDER BY seq", run_id, after)
    return [{"seq": r["seq"], "ts": r["ts"], "event": json.loads(r["data"])} for r in rows]


def save_conversation(key: str, messages: Any) -> None:
    _run(
        "INSERT INTO conversation (run_id, messages) VALUES (?, ?) "
        "ON CONFLICT(run_id) DO UPDATE SET messages = excluded.messages",
        key,
        json.dumps(messages),
    )


def load_conversation(key: str) -> Any:
    row = _one("SELECT messages FROM conversation WHERE run_id = ?", key)
    return json.loads(row["messages"]) if row else None


def save_feedback(run_id: str, rating: str, note: str) -> None:
    _run(
        "INSERT INTO feedback (run_id, rating, note, ts) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(run_id) DO UPDATE SET rating = excluded.rating, note = excluded.note, "
        "ts = excluded.ts",
        run_id,
        rating,
        note,
        now_ms(),
    )


def get_feedback(run_id: str) -> dict[str, str] | None:
    row = _one("SELECT rating, note FROM feedback WHERE run_id = ?", run_id)
    return {"rating": row["rating"], "note": row["note"]} if row else None


def skill_rows() -> dict[str, dict[str, Any]]:
    return {row["name"]: dict(row) for row in _all("SELECT * FROM skills")}


def put_skill(name: str, **fields: Any) -> None:
    current = skill_rows().get(name, {"enabled": 1})
    merged = {**current, **{k: v for k, v in fields.items() if k != "name"}}
    _run(
        "INSERT INTO skills (name, title, description, content, enabled) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET title = excluded.title, "
        "description = excluded.description, content = excluded.content, "
        "enabled = excluded.enabled",
        name,
        merged.get("title"),
        merged.get("description"),
        merged.get("content"),
        1 if merged["enabled"] else 0,
    )


def delete_skill(name: str) -> None:
    _run("DELETE FROM skills WHERE name = ?", name)
