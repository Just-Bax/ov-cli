from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

RENAMES = (("settings", "setting"), ("runs", "run"), ("events", "event"), ("skills", "skill"))
TEXT_KEYS = (
    ("setting", "key"),
    ("run", "id"),
    ("conversation", "run_id"),
    ("settled", "run_id"),
    ("pinned", "run_id"),
    ("snoozed", "run_id"),
    ("feedback", "run_id"),
    ("skill", "name"),
)


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS watches")

    for old, new in RENAMES:
        op.rename_table(old, new)
    for table, key in TEXT_KEYS:
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.alter_column(key, existing_type=sa.Text(), nullable=False)

    op.execute(
        "CREATE TABLE usage_new (id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, "
        "ts INTEGER NOT NULL, model TEXT NOT NULL, kind TEXT NOT NULL, tokens TEXT NOT NULL, nano INTEGER NOT NULL)"
    )

    op.execute(
        "INSERT INTO usage_new (run_id, ts, model, kind, tokens, nano) "
        "SELECT run_id, ts, model, kind, tokens, nano FROM usage ORDER BY rowid"
    )

    op.execute("DROP TABLE usage")
    op.rename_table("usage_new", "usage")
    op.create_index("usage_by_run", "usage", ["run_id"])
    op.create_index("usage_by_time", "usage", ["ts"])


def downgrade() -> None:
    op.execute(
        "CREATE TABLE usage_old (run_id TEXT NOT NULL, ts INTEGER NOT NULL, model TEXT NOT NULL, "
        "kind TEXT NOT NULL, tokens TEXT NOT NULL, nano INTEGER NOT NULL)"
    )

    op.execute(
        "INSERT INTO usage_old (run_id, ts, model, kind, tokens, nano) "
        "SELECT run_id, ts, model, kind, tokens, nano FROM usage ORDER BY id"
    )

    op.execute("DROP TABLE usage")
    op.rename_table("usage_old", "usage")
    op.create_index("usage_by_run", "usage", ["run_id"])
    op.create_index("usage_by_time", "usage", ["ts"])
    for old, new in RENAMES:
        op.rename_table(new, old)
