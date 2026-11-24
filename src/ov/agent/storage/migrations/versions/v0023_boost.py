from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

REASONING_LEVELS = ("none", "low", "medium", "high", "xhigh", "max")
PREFERENCE_COLUMNS = (
    "id, provider, reasoning, max_steps, workspace, workspace_notes, full_name, instructions, notify, tab_badge, "
    "compact_branches, updated_at"
)
COPY_PREFERENCES = f"""
INSERT INTO new_preference ({PREFERENCE_COLUMNS}, boost)
SELECT {PREFERENCE_COLUMNS}, 0
FROM preference
"""


def upgrade() -> None:
    levels = ", ".join(f"'{level}'" for level in REASONING_LEVELS)
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
        sa.Column("boost", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="single_row"),
        sa.CheckConstraint(f"reasoning IS NULL OR reasoning IN ({levels})", name="reasoning_valid"),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 500", name="max_steps_valid"),
        sa.CheckConstraint("notify IN (0, 1)", name="notify_valid"),
        sa.CheckConstraint("tab_badge IN (0, 1)", name="tab_badge_valid"),
        sa.CheckConstraint("compact_branches IN (0, 1)", name="compact_branches_valid"),
        sa.CheckConstraint("boost IN (0, 1)", name="boost_valid"),
    )

    op.execute(COPY_PREFERENCES)
    op.drop_table("preference")
    op.rename_table("new_preference", "preference")


def downgrade() -> None:
    raise NotImplementedError("This schema cannot be downgraded; restore agent.0022.bak.db instead.")
