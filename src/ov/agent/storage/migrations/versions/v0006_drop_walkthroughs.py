from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
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
    op.drop_table("walkthrough_run")
    op.drop_table("walkthrough")
    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check(EVENT_TYPES))


def downgrade() -> None:
    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check((*EVENT_TYPES, "walkthrough")))
