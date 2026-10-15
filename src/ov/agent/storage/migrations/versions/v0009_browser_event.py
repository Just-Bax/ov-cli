from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
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
)


def _check(types: tuple[str, ...]) -> str:
    return "type IN (" + ", ".join(repr(t) for t in types) + ")"


def upgrade() -> None:
    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check((*EVENT_TYPES, "browser")))


def downgrade() -> None:
    op.execute("DELETE FROM event WHERE type = 'browser'")
    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check(EVENT_TYPES))
