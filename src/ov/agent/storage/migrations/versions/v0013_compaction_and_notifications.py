from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
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
)
NEW_EVENT_TYPES = ("compact", "context")
USAGE_KINDS = ("turn", "step", "naming", "guard")


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(repr(v) for v in values) + ")"


def upgrade() -> None:
    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check("type", (*EVENT_TYPES, *NEW_EVENT_TYPES)))

    with op.batch_alter_table("usage") as batch:
        batch.drop_constraint("kind_valid", type_="check")
        batch.create_check_constraint("kind_valid", _check("kind", (*USAGE_KINDS, "compact")))

    op.execute(
        "ALTER TABLE preference ADD COLUMN notify INTEGER NOT NULL DEFAULT 0 "
        "CONSTRAINT notify_valid CHECK (notify IN (0, 1))"
    )
    op.execute(
        "ALTER TABLE preference ADD COLUMN tab_badge INTEGER NOT NULL DEFAULT 1 "
        "CONSTRAINT tab_badge_valid CHECK (tab_badge IN (0, 1))"
    )
    op.execute(
        "ALTER TABLE preference ADD COLUMN compact_window INTEGER "
        "CONSTRAINT compact_window_valid CHECK (compact_window IS NULL OR compact_window > 0)"
    )


def downgrade() -> None:
    with op.batch_alter_table("preference") as batch:
        for column in ("notify", "tab_badge", "compact_window"):
            batch.drop_constraint(f"{column}_valid", type_="check")
            batch.drop_column(column)

    op.execute("DELETE FROM usage WHERE kind = 'compact'")

    with op.batch_alter_table("usage") as batch:
        batch.drop_constraint("kind_valid", type_="check")
        batch.create_check_constraint("kind_valid", _check("kind", USAGE_KINDS))

    op.execute("DELETE FROM event WHERE type IN ('compact', 'context')")

    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("type_valid", type_="check")
        batch.create_check_constraint("type_valid", _check("type", EVENT_TYPES))
