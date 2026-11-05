from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

STATUSES = ("queued", "running", "waiting", "done", "error", "cancelled")
ACCESS_MODES = ("read", "ask", "auto", "full")
ORIGINS = ("branch",)
REASONING_LEVELS = ("none", "low", "medium", "high", "xhigh", "max")
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
)
REBUILT = ("thread", "event", "preference")
THREAD_COLUMNS = (
    "id, title, instance, status, provider, model, access, parent_id, origin, origin_turn_id, inherited_until, "
    "pinned_at, snoozed_until, settled_at, status_changed_at, seen_at, created_at, updated_at"
)
COPY_THREADS = f"""
INSERT INTO new_thread ({THREAD_COLUMNS})
SELECT {THREAD_COLUMNS.replace("origin,", "CASE WHEN origin IS NULL THEN NULL ELSE 'branch' END,", 1)}
FROM thread
"""
COPY_EVENTS = """
INSERT INTO new_event (thread_id, position, type, data, created_at)
SELECT thread_id, position, type, data, created_at
FROM event
WHERE type != 'branch_result'
"""
PREFERENCE_COLUMNS = (
    "id, provider, reasoning, max_steps, workspace, workspace_notes, full_name, instructions, notify, tab_badge, "
    "updated_at"
)
COPY_PREFERENCES = f"""
INSERT INTO new_preference ({PREFERENCE_COLUMNS}, compact_branches)
SELECT {PREFERENCE_COLUMNS}, 0
FROM preference
"""


def _one_of(column: str, values: tuple[str, ...], nullable: bool = False) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    condition = f"{column} IN ({allowed})"
    return sa.CheckConstraint(f"{column} IS NULL OR {condition}" if nullable else condition, name=f"{column}_valid")


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
        sa.Column("parent_id", sa.Text(), sa.ForeignKey("thread.id", ondelete="SET NULL")),
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
        sa.Column("thread_id", sa.Text(), sa.ForeignKey("thread.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        _one_of("type", EVENT_TYPES),
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
        sa.Column("compact_branches", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="single_row"),
        _one_of("reasoning", REASONING_LEVELS, nullable=True),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 500", name="max_steps_valid"),
        sa.CheckConstraint("notify IN (0, 1)", name="notify_valid"),
        sa.CheckConstraint("tab_badge IN (0, 1)", name="tab_badge_valid"),
        sa.CheckConstraint("compact_branches IN (0, 1)", name="compact_branches_valid"),
    )


def upgrade() -> None:
    _create_tables()
    op.execute(COPY_THREADS)
    op.execute(COPY_EVENTS)
    op.execute(COPY_PREFERENCES)

    for table in REBUILT:
        op.drop_table(table)
    for table in REBUILT:
        op.rename_table(f"new_{table}", table)

    op.create_index("thread_by_updated", "thread", ["updated_at"])
    op.create_index("thread_by_settled", "thread", ["settled_at"])
    op.create_index("thread_by_status", "thread", ["status"])
    op.create_index("thread_by_parent", "thread", ["parent_id"])
    op.drop_table("finding")


def downgrade() -> None:
    raise NotImplementedError("This schema cannot be downgraded; restore agent.0021.bak.db instead.")
