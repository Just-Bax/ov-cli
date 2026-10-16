from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

ACCESS_MODES = ("read", "ask", "auto")
DOWNGRADED_FULL = "auto"


def _check(modes: tuple[str, ...]) -> str:
    return "access IN (" + ", ".join(repr(m) for m in modes) + ")"


def upgrade() -> None:
    with op.batch_alter_table("thread") as batch:
        batch.drop_constraint("access_valid", type_="check")
        batch.create_check_constraint("access_valid", _check((*ACCESS_MODES, "full")))


def downgrade() -> None:
    op.execute(f"UPDATE thread SET access = '{DOWNGRADED_FULL}' WHERE access = 'full'")
    with op.batch_alter_table("thread") as batch:
        batch.drop_constraint("access_valid", type_="check")
        batch.create_check_constraint("access_valid", _check(ACCESS_MODES))
