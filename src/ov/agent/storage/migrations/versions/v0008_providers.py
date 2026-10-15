from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

PROVIDERS = ("copilot", "claude")
TABLES = ("preference", "thread", "usage")
EXISTING_PROVIDER = "copilot"


def _check() -> str:
    return "provider IN (" + ", ".join(repr(p) for p in PROVIDERS) + ")"


def upgrade() -> None:
    for table in TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN provider TEXT NOT NULL DEFAULT '{EXISTING_PROVIDER}' "
            f"CONSTRAINT provider_valid CHECK ({_check()})"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN provider")
