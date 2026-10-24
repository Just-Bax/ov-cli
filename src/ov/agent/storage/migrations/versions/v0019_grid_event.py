from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

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
    "queue",
    "rewind",
    "access",
    "browser",
    "compact",
    "context",
)


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(v) for v in values) + ")"


def upgrade() -> None:
    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check("type", (*EVENT_TYPES, "grid")))


def downgrade() -> None:
    op.execute("DELETE FROM event WHERE type = 'grid'")

    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check("type", EVENT_TYPES))
