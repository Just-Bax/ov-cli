from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

STATUSES = ("queued", "running", "waiting", "done", "error", "cancelled")
ACCESS_MODES = ("read", "ask", "auto", "full")
ORIGINS = ("branch", "summary", "findings")
EVENT_TYPES = (
    "status",
    "meta",
    "tool",
    "agent_message",
    "user_message",
    "change",
    "grid",
    "edit",
    "outcome",
    "question",
    "login",
    "queue_add",
    "queue_remove",
    "queue_order",
    "rewind",
    "access",
    "browser",
    "compact",
    "context",
    "branch_result",
)
USAGE_KINDS = ("turn", "agent", "browser", "title", "guard", "summary")
REASONING_LEVELS = ("none", "low", "medium", "high", "xhigh", "max")
RENAMED_EVENTS = {
    "user": "user_message",
    "message": "agent_message",
    "queued": "queue_add",
    "unqueue": "queue_remove",
    "queue": "queue_order",
}
RENAMED_USAGE = {"naming": "title", "step": "agent", "compact": "summary"}
REBUILT = ("thread", "event", "usage", "preference")

COPY_THREADS = """
INSERT INTO new_thread (
    id, title, instance, status, provider, model, access, parent_id, origin, origin_turn_id, inherited_until,
    pinned_at, snoozed_until, settled_at, status_changed_at, seen_at, created_at, updated_at
)
SELECT
    t.id, t.title, t.instance, t.status, t.provider, t.model, t.access, link.parent_id,
    CASE WHEN link.parent_id IS NULL THEN NULL ELSE 'summary' END, NULL, 0,
    t.pinned_at, t.snoozed_until, t.settled_at, t.status_at, t.seen_at, t.created_at, t.updated_at
FROM thread t
LEFT JOIN (
    SELECT e.thread_id, MAX(json_extract(e.data, '$.continuedFrom.id')) AS parent_id
    FROM event e
    WHERE e.type = 'meta' AND json_extract(e.data, '$.continuedFrom.id') IN (SELECT id FROM thread)
    GROUP BY e.thread_id
) link ON link.thread_id = t.id
"""
COPY_EVENTS = """
INSERT INTO new_event (thread_id, position, type, data, created_at)
SELECT thread_id, position, {kind}, json_remove(data, '$.continuedFrom', '$.continuedIn'), created_at
FROM event
WHERE NOT (type = 'meta' AND json_remove(data, '$.continuedFrom', '$.continuedIn') = '{{}}')
"""
COPY_USAGE = """
INSERT INTO new_usage (
    id, thread_id, provider, model, kind, input_tokens, cache_read_tokens, cache_write_tokens, output_tokens,
    cost_nano, created_at
)
SELECT id, thread_id, provider, model, {kind}, input_tokens, cached_tokens, cache_write_tokens, output_tokens,
    cost_nano, created_at
FROM usage
"""
COPY_PREFERENCES = """
INSERT INTO new_preference (
    id, provider, reasoning, max_steps, workspace, workspace_notes, full_name, instructions, notify, tab_badge,
    updated_at
)
SELECT id, provider, reasoning, max_steps, workspace, workspace_notes, full_name, instructions, notify, tab_badge,
    updated_at
FROM preference
"""


def _one_of(column: str, values: tuple[str, ...], nullable: bool = False) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    condition = f"{column} IN ({allowed})"
    return sa.CheckConstraint(f"{column} IS NULL OR {condition}" if nullable else condition, name=f"{column}_valid")


def _renamed(column: str, names: dict[str, str]) -> str:
    cases = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in names.items())
    return f"CASE {column} {cases} ELSE {column} END"


def _thread_fk(ondelete: str = "CASCADE") -> sa.ForeignKey:
    return sa.ForeignKey("thread.id", ondelete=ondelete)


def _create_tables() -> None:
    op.create_table(
        "new_thread",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("instance", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("access", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Text(), _thread_fk("SET NULL")),
        sa.Column("origin", sa.Text()),
        sa.Column("origin_turn_id", sa.Text()),
        sa.Column("inherited_until", sa.Integer(), nullable=False),
        sa.Column("pinned_at", sa.Integer()),
        sa.Column("snoozed_until", sa.Integer()),
        sa.Column("settled_at", sa.Integer()),
        sa.Column("status_changed_at", sa.Integer()),
        sa.Column("seen_at", sa.Integer()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        _one_of("status", STATUSES),
        _one_of("access", ACCESS_MODES),
        _one_of("origin", ORIGINS, nullable=True),
        sa.CheckConstraint("inherited_until >= 0", name="inherited_until_valid"),
    )
    op.create_table(
        "new_event",
        sa.Column("thread_id", sa.Text(), _thread_fk(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        _one_of("type", EVENT_TYPES),
    )
    op.create_table(
        "new_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.Text(), _thread_fk(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_nano", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        _one_of("kind", USAGE_KINDS),
    )
    op.create_table(
        "new_preference",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text()),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("workspace", sa.Text()),
        sa.Column("workspace_notes", sa.Text()),
        sa.Column("full_name", sa.Text()),
        sa.Column("instructions", sa.Text()),
        sa.Column("notify", sa.Integer(), nullable=False),
        sa.Column("tab_badge", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="single_row"),
        _one_of("reasoning", REASONING_LEVELS, nullable=True),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 500", name="max_steps_valid"),
        sa.CheckConstraint("notify IN (0, 1)", name="notify_valid"),
        sa.CheckConstraint("tab_badge IN (0, 1)", name="tab_badge_valid"),
    )


def _create_indexes() -> None:
    op.create_index("thread_by_updated", "thread", ["updated_at"])
    op.create_index("thread_by_settled", "thread", ["settled_at"])
    op.create_index("thread_by_status", "thread", ["status"])
    op.create_index("thread_by_parent", "thread", ["parent_id"])
    op.create_index("usage_by_thread", "usage", ["thread_id"])
    op.create_index("usage_by_created", "usage", ["created_at"])


def upgrade() -> None:
    _create_tables()
    op.execute(COPY_THREADS)
    op.execute(COPY_EVENTS.format(kind=_renamed("type", RENAMED_EVENTS)))
    op.execute(COPY_USAGE.format(kind=_renamed("kind", RENAMED_USAGE)))
    op.execute(COPY_PREFERENCES)

    for table in REBUILT:
        op.drop_table(table)
    for table in REBUILT:
        op.rename_table(f"new_{table}", table)
    _create_indexes()
    op.drop_table("attachment")

    op.create_table(
        "finding",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.Text(), _thread_fk(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("turn_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )
    op.create_index("finding_by_thread", "finding", ["thread_id"])


def downgrade() -> None:
    raise NotImplementedError("The thread tree schema cannot be downgraded; restore agent.0020.bak.db instead.")
