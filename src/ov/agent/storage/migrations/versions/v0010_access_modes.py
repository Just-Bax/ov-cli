from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

ACCESS_MODES = ("read", "ask", "auto")
READ_ONLY = "read"
ASK_FIRST = "ask"


def _check() -> str:
    return "access IN (" + ", ".join(repr(m) for m in ACCESS_MODES) + ")"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE thread ADD COLUMN access TEXT NOT NULL DEFAULT '{READ_ONLY}' "
        f"CONSTRAINT access_valid CHECK ({_check()})"
    )
    op.execute(f"UPDATE thread SET access = '{ASK_FIRST}' WHERE allow_write = 1")
    op.execute(
        "UPDATE event SET data = json_set(json_remove(data, '$.write'), '$.access', CASE WHEN "
        f"json_extract(data, '$.write') THEN '{ASK_FIRST}' ELSE '{READ_ONLY}' END) WHERE type = 'access'"
    )
    with op.batch_alter_table("thread") as batch:
        batch.drop_constraint("allow_write_valid", type_="check")
        batch.drop_column("allow_write")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE thread ADD COLUMN allow_write INTEGER NOT NULL DEFAULT 0 "
        "CONSTRAINT allow_write_valid CHECK (allow_write IN (0, 1))"
    )
    op.execute(f"UPDATE thread SET allow_write = 1 WHERE access != '{READ_ONLY}'")
    op.execute(
        "UPDATE event SET data = json_set(json_remove(data, '$.access'), '$.write', json(CASE WHEN "
        f"json_extract(data, '$.access') = '{READ_ONLY}' THEN 'false' ELSE 'true' END)) WHERE type = 'access'"
    )
    with op.batch_alter_table("thread") as batch:
        batch.drop_constraint("access_valid", type_="check")
        batch.drop_column("access")
