from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

RUN_STATUSES = ("pending", "running", "passed", "failed", "blocked", "error", "stopped")


def upgrade() -> None:
    op.create_table(
        "walkthrough",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )
    op.create_index("walkthrough_by_created", "walkthrough", ["created_at"])

    op.create_table(
        "walkthrough_run",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("walkthrough_id", sa.Text(), sa.ForeignKey("walkthrough.id", ondelete="SET NULL")),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.Integer()),
        sa.CheckConstraint(f"status IN ({', '.join(repr(s) for s in RUN_STATUSES)})", name="status_valid"),
    )
    op.create_index("walkthrough_run_by_walkthrough", "walkthrough_run", ["walkthrough_id"])
    op.create_index("walkthrough_run_by_created", "walkthrough_run", ["created_at"])


def downgrade() -> None:
    op.drop_table("walkthrough_run")
    op.drop_table("walkthrough")
