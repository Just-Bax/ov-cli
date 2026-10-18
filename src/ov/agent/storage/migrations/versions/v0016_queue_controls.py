from __future__ import annotations

from alembic import op

revision = "0016"
down_revision = "0015"
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
    "rewind",
    "access",
    "browser",
    "compact",
    "context",
)
FOLLOW_UPS = ("steer", "queue")


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(v) for v in values) + ")"


def upgrade() -> None:
    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check("type", (*EVENT_TYPES, "queue")))

    op.execute(
        "ALTER TABLE preference ADD COLUMN follow_up TEXT NOT NULL DEFAULT 'queue' "
        f"CONSTRAINT follow_up_valid CHECK ({_check('follow_up', FOLLOW_UPS)})"
    )


def downgrade() -> None:
    with op.batch_alter_table("preference") as batch:
        batch.drop_constraint("follow_up_valid", type_="check")
        batch.drop_column("follow_up")

    op.execute("DELETE FROM event WHERE type = 'queue'")

    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check("type", EVENT_TYPES))
