from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

PROVIDERS = ("copilot", "claude")
PROVIDER_TABLES = ("preference", "thread", "usage")
PROFILE_COLUMNS = ("full_name", "instructions")
SESSION_META = """
UPDATE event
SET data = json_set(
    json_remove(data, '$.claude'),
    '$.session',
    json(json_set(
        json_remove(json_extract(data, '$.claude'), '$.session'), '$.id', json_extract(data, '$.claude.session')
    ))
)
WHERE type = 'meta' AND json_extract(data, '$.claude') IS NOT NULL
"""
CLAUDE_META = """
UPDATE event
SET data = json_set(
    json_remove(data, '$.session'),
    '$.claude',
    json(json_set(
        json_remove(json_extract(data, '$.session'), '$.id'), '$.session', json_extract(data, '$.session.id')
    ))
)
WHERE type = 'meta' AND json_extract(data, '$.session') IS NOT NULL
"""


def _provider_check() -> str:
    return "provider IN (" + ", ".join(repr(p) for p in PROVIDERS) + ")"


def upgrade() -> None:
    for table in PROVIDER_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint("provider_valid", type_="check")

    with op.batch_alter_table("preference") as batch:
        for column in PROFILE_COLUMNS:
            batch.add_column(sa.Column(column, sa.Text(), nullable=True))

    op.execute(SESSION_META)


def downgrade() -> None:
    op.execute(CLAUDE_META)

    with op.batch_alter_table("preference") as batch:
        for column in PROFILE_COLUMNS:
            batch.drop_column(column)

    for table in PROVIDER_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint("provider_valid", _provider_check())
