from __future__ import annotations

import json
import time
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

THREAD_STATUSES = ("queued", "running", "waiting", "done", "error", "cancelled")
EVENT_TYPES = (
    "status",
    "meta",
    "tool",
    "message",
    "user",
    "change",
    "edit",
    "outcome",
    "question",
    "login",
    "queued",
    "unqueue",
    "rewind",
    "access",
)
MESSAGE_ROLES = ("system", "user", "assistant", "tool")
USAGE_KINDS = ("turn", "step", "naming", "reply")
REASONING_LEVELS = ("none", "low", "medium", "high", "xhigh", "max")
FOLLOW_UPS = ("steer", "queue")
SKILL_SOURCES = ("bundled", "custom")
TOKEN_COLUMNS = {
    "input": "input_tokens",
    "cache_read": "cached_tokens",
    "cache_write": "cache_write_tokens",
    "output": "output_tokens",
}
MESSAGE_KEYS = {"role", "content", "tool_calls", "tool_call_id"}
TURNS_SUFFIX = "#turns"
START_TURN = "u_start"
DEFAULT_MAX_STEPS = 80
OLD_TABLES = ("run", "event", "usage", "skill")
DROPPED = ("conversation", "settled", "pinned", "snoozed", "feedback", "setting")


def _one_of(column: str, values: tuple[str, ...], nullable: bool = False) -> sa.CheckConstraint:
    condition = f"{column} IN ({', '.join(repr(v) for v in values)})"
    return sa.CheckConstraint(f"{column} IS NULL OR {condition}" if nullable else condition, name=f"{column}_valid")


def _thread_fk() -> sa.ForeignKey:
    return sa.ForeignKey("thread.id", ondelete="CASCADE")


def _create_thread() -> None:
    op.create_table(
        "thread",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("instance", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("allow_write", sa.Integer(), nullable=False),
        sa.Column("pinned_at", sa.Integer()),
        sa.Column("snoozed_until", sa.Integer()),
        sa.Column("settled_at", sa.Integer()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        _one_of("status", THREAD_STATUSES),
        sa.CheckConstraint("allow_write IN (0, 1)", name="allow_write_valid"),
    )
    op.create_index("thread_by_created", "thread", ["created_at"])
    op.create_index("thread_by_settled", "thread", ["settled_at"])
    op.create_index("thread_by_status", "thread", ["status"])


def _create_children() -> None:
    op.create_table(
        "attachment",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.Text(), _thread_fk(), nullable=False),
        sa.Column("turn_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
    )
    op.create_index("attachment_by_thread", "attachment", ["thread_id"])
    op.create_table(
        "event",
        sa.Column("thread_id", sa.Text(), _thread_fk(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        _one_of("type", EVENT_TYPES),
    )
    op.create_table(
        "message",
        sa.Column("thread_id", sa.Text(), _thread_fk(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("tool_calls", sa.Text()),
        sa.Column("tool_call_id", sa.Text()),
        sa.Column("turn_id", sa.Text()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        _one_of("role", MESSAGE_ROLES),
    )
    op.create_table(
        "usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.Text(), _thread_fk(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_nano", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        _one_of("kind", USAGE_KINDS),
    )
    op.create_index("usage_by_thread", "usage", ["thread_id"])
    op.create_index("usage_by_created", "usage", ["created_at"])


def _create_settings() -> None:
    op.create_table(
        "preference",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("default_model", sa.Text()),
        sa.Column("fast_model", sa.Text()),
        sa.Column("reasoning", sa.Text()),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("follow_up", sa.Text(), nullable=False),
        sa.Column("workspace", sa.Text()),
        sa.Column("workspace_notes", sa.Text()),
        sa.Column("expand_tools", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="single_row"),
        _one_of("reasoning", REASONING_LEVELS, nullable=True),
        _one_of("follow_up", FOLLOW_UPS),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 500", name="max_steps_valid"),
        sa.CheckConstraint("expand_tools IN (0, 1)", name="expand_tools_valid"),
    )
    op.create_table(
        "skill",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        _one_of("source", SKILL_SOURCES),
        sa.CheckConstraint("enabled IN (0, 1)", name="enabled_valid"),
    )


def _events_of(bind: sa.Connection) -> dict[str, list[tuple[int, int, dict[str, Any]]]]:
    events: dict[str, list[tuple[int, int, dict[str, Any]]]] = {}
    for run_id, seq, ts, data in bind.execute(
        sa.text("SELECT run_id, seq, ts, data FROM event_old ORDER BY run_id, seq")
    ):
        events.setdefault(run_id, []).append((seq, ts, json.loads(data)))
    return events


def _merged(events: list[tuple[int, int, dict[str, Any]]]) -> list[tuple[int, int, str, dict[str, Any]]]:
    final = {e["messageId"] for _, _, e in events if e["type"] == "message"}
    texts: dict[str, list[str]] = {}
    for _, _, event in events:
        if event["type"] == "text":
            texts.setdefault(event["messageId"], []).append(event["delta"])

    merged: list[tuple[int, int, str, dict[str, Any]]] = []
    for seq, ts, event in events:
        kind = event.pop("type")
        if kind == "text":
            message_id = event["messageId"]
            if message_id in final or message_id not in texts:
                continue
            merged.append(
                (seq, ts, "message", {"messageId": message_id, "text": "".join(texts.pop(message_id)), "ts": ts})
            )
        elif kind in EVENT_TYPES:
            merged.append((seq, ts, kind, event))
    return merged


def _allow_write(data: dict[str, Any], events: list[tuple[int, int, str, dict[str, Any]]]) -> bool:
    allowed = bool(data.get("allowWrite"))
    for _, _, kind, event in events:
        if kind == "access":
            allowed = bool(event["write"])
    return allowed


def _copy_threads(bind: sa.Connection) -> set[str]:
    events = _events_of(bind)
    rows = bind.execute(
        sa.text(
            "SELECT r.*, s.ts AS settled_at, p.ts AS pinned_at, z.until AS snoozed_until FROM run_old r "
            "LEFT JOIN settled s ON s.run_id = r.id LEFT JOIN pinned p ON p.run_id = r.id "
            "LEFT JOIN snoozed z ON z.run_id = r.id"
        )
    ).mappings()
    threads: set[str] = set()
    for row in rows:
        data = json.loads(row["input"])
        merged = _merged(events.get(row["id"], []))
        bind.execute(
            sa.text(
                "INSERT INTO thread VALUES (:id, :title, :instance, :status, :model, :prompt, :allow_write, "
                ":pinned_at, :snoozed_until, :settled_at, :created_at, :updated_at)"
            ),
            {
                **{k: row[k] for k in ("id", "title", "instance", "status", "model", "created_at", "updated_at")},
                **{k: row[k] for k in ("pinned_at", "snoozed_until", "settled_at")},
                "prompt": str(data.get("prompt") or ""),
                "allow_write": int(_allow_write(data, merged)),
            },
        )
        for seq, ts, kind, event in merged:
            bind.execute(
                sa.text("INSERT INTO event VALUES (:thread, :position, :type, :data, :created_at)"),
                {"thread": row["id"], "position": seq, "type": kind, "data": json.dumps(event), "created_at": ts},
            )
        for attachment in data.get("attachments") or []:
            bind.execute(
                sa.text("INSERT INTO attachment (thread_id, turn_id, name, created_at) VALUES (:t, :turn, :name, :at)"),
                {"t": row["id"], "turn": START_TURN, "name": str(attachment["name"]), "at": row["created_at"]},
            )
        threads.add(row["id"])
    return threads


def _copy_messages(bind: sa.Connection, threads: set[str]) -> None:
    stored = dict(bind.execute(sa.text("SELECT run_id, messages FROM conversation")).all())
    created = dict(bind.execute(sa.text("SELECT id, created_at FROM thread")).all())
    for thread_id in threads:
        if thread_id not in stored:
            continue
        turns = json.loads(stored.get(thread_id + TURNS_SUFFIX) or "{}")
        turn_at = {turn["index"]: turn_id for turn_id, turn in turns.items()}
        for position, message in enumerate(json.loads(stored[thread_id])):
            extra = set(message) - MESSAGE_KEYS
            if extra:
                raise ValueError(f"Thread {thread_id} has a model message with unknown fields: {sorted(extra)}")
            bind.execute(
                sa.text("INSERT INTO message VALUES (:t, :p, :role, :content, :calls, :call_id, :turn, :at)"),
                {
                    "t": thread_id,
                    "p": position,
                    "role": message["role"],
                    "content": None if message.get("content") is None else json.dumps(message["content"]),
                    "calls": json.dumps(message["tool_calls"]) if message.get("tool_calls") else None,
                    "call_id": message.get("tool_call_id"),
                    "turn": turn_at.get(position),
                    "at": created[thread_id],
                },
            )


def _copy_usage(bind: sa.Connection, threads: set[str]) -> None:
    for run_id, ts, model, kind, tokens, nano in bind.execute(
        sa.text("SELECT run_id, ts, model, kind, tokens, nano FROM usage_old ORDER BY id")
    ):
        if run_id not in threads:
            continue
        counts = json.loads(tokens)
        unknown = set(counts) - set(TOKEN_COLUMNS)
        if unknown:
            raise ValueError(f"Usage row of {run_id} has unknown token types: {sorted(unknown)}")
        columns = {column: int(counts.get(key, 0)) for key, column in TOKEN_COLUMNS.items()}
        bind.execute(
            sa.text(
                "INSERT INTO usage (thread_id, model, kind, input_tokens, cached_tokens, cache_write_tokens, "
                "output_tokens, cost_nano, created_at) VALUES (:t, :model, :kind, :input_tokens, :cached_tokens, "
                ":cache_write_tokens, :output_tokens, :nano, :at)"
            ),
            {"t": run_id, "model": model, "kind": kind, "nano": nano, "at": ts, **columns},
        )


def _copy_preferences(bind: sa.Connection, now: int) -> None:
    stored = {key: json.loads(value) for key, value in bind.execute(sa.text("SELECT key, value FROM setting"))}
    bind.execute(
        sa.text(
            "INSERT INTO preference VALUES (1, :default_model, :fast_model, :reasoning, :max_steps, :follow_up, "
            ":workspace, :workspace_notes, :expand_tools, :now)"
        ),
        {
            "default_model": stored.get("defaultModel") or None,
            "fast_model": stored.get("fastModel") or None,
            "reasoning": stored.get("reasoning") or None,
            "max_steps": int(stored.get("maxSteps") or DEFAULT_MAX_STEPS),
            "follow_up": stored.get("followUp") or "steer",
            "workspace": stored.get("workspace") or None,
            "workspace_notes": stored.get("workspaceNotes") or None,
            "expand_tools": int(bool(stored.get("expandTools"))),
            "now": now,
        },
    )


def _copy_skills(bind: sa.Connection, now: int) -> None:
    insert = sa.text("INSERT INTO skill VALUES (:name, :source, :title, :description, :content, :enabled, :now, :now)")
    for row in bind.execute(sa.text("SELECT * FROM skill_old")).mappings():
        bundled = row["title"] is None
        if bundled and row["content"] is not None:
            copy = {"title": f"{row['name']} (edited)", "description": "", "content": row["content"]}
            bind.execute(
                insert, {"name": f"{row['name']}-edited", "source": "custom", "enabled": 1, "now": now, **copy}
            )
        values = {
            "name": row["name"],
            "source": "bundled" if bundled else "custom",
            "title": row["name"] if bundled else row["title"],
            "description": "" if bundled else row["description"] or "",
            "content": "" if bundled else row["content"] or "",
            "enabled": 0 if bundled and row["content"] is not None else int(bool(row["enabled"])),
            "now": now,
        }
        bind.execute(insert, values)


def upgrade() -> None:
    bind = op.get_bind()
    now = int(time.time() * 1000)
    for table in OLD_TABLES:
        op.rename_table(table, f"{table}_old")
    op.execute("DROP INDEX IF EXISTS usage_by_run")
    op.execute("DROP INDEX IF EXISTS usage_by_time")
    _create_thread()
    _create_children()
    _create_settings()

    threads = _copy_threads(bind)
    _copy_messages(bind, threads)
    _copy_usage(bind, threads)
    _copy_preferences(bind, now)
    _copy_skills(bind, now)

    for table in (*(f"{t}_old" for t in OLD_TABLES), *DROPPED):
        op.drop_table(table)


def downgrade() -> None:
    raise NotImplementedError("0003 reshapes the data; restore agent.0002.bak.db to go back.")
