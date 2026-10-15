from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

USAGE_KINDS = ("turn", "step", "naming", "guard")
OLD_USAGE_KINDS = ("turn", "step", "naming", "reply")


def _check(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(repr(k) for k in kinds) + ")"


def upgrade() -> None:
    op.execute("UPDATE usage SET kind = 'naming' WHERE kind = 'reply'")
    with op.batch_alter_table("usage") as batch:
        batch.drop_constraint("kind_valid", type_="check")
        batch.create_check_constraint("kind_valid", _check(USAGE_KINDS))


def downgrade() -> None:
    op.execute("UPDATE usage SET kind = 'naming' WHERE kind = 'guard'")
    with op.batch_alter_table("usage") as batch:
        batch.drop_constraint("kind_valid", type_="check")
        batch.create_check_constraint("kind_valid", _check(OLD_USAGE_KINDS))
