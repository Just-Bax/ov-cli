from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

COLUMNS = ("status_at", "seen_at")


def upgrade() -> None:
    with op.batch_alter_table("thread") as batch:
        for column in COLUMNS:
            batch.add_column(sa.Column(column, sa.Integer()))


def downgrade() -> None:
    with op.batch_alter_table("thread") as batch:
        for column in COLUMNS:
            batch.drop_column(column)
