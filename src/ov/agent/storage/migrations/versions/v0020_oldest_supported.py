from __future__ import annotations

revision = "0020"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    raise RuntimeError("Revision 0020 is the oldest supported schema; databases start at it or at head.")


def downgrade() -> None:
    raise RuntimeError("Revision 0020 is the oldest supported schema.")
