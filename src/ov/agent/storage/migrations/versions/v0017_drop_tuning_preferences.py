from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

FOLLOW_UPS = ("steer", "queue")


def upgrade() -> None:
    with op.batch_alter_table("preference") as batch:
        batch.drop_constraint("follow_up_valid", type_="check")
        batch.drop_constraint("expand_tools_valid", type_="check")
        batch.drop_constraint("compact_window_valid", type_="check")
        batch.drop_column("follow_up")
        batch.drop_column("expand_tools")
        batch.drop_column("compact_window")


def downgrade() -> None:
    with op.batch_alter_table("preference") as batch:
        batch.add_column(sa.Column("follow_up", sa.Text(), nullable=False, server_default="queue"))
        batch.add_column(sa.Column("expand_tools", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("compact_window", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "follow_up_valid", "follow_up IN (" + ", ".join(repr(v) for v in FOLLOW_UPS) + ")"
        )
        batch.create_check_constraint("expand_tools_valid", "expand_tools IN (0, 1)")
        batch.create_check_constraint("compact_window_valid", "compact_window IS NULL OR compact_window > 0")
