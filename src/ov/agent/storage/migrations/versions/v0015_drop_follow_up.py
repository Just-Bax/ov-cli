from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

FOLLOW_UPS = ("steer", "queue")


def upgrade() -> None:
    with op.batch_alter_table("preference") as batch:
        batch.drop_constraint("follow_up_valid", type_="check")
        batch.drop_column("follow_up")


def downgrade() -> None:
    with op.batch_alter_table("preference") as batch:
        batch.add_column(sa.Column("follow_up", sa.Text(), nullable=False, server_default="queue"))
        batch.create_check_constraint(
            "follow_up_valid", "follow_up IN (" + ", ".join(repr(v) for v in FOLLOW_UPS) + ")"
        )
