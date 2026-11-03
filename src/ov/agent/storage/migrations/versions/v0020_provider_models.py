from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

MODEL_COLUMNS = ("default_model", "fast_model")
COPY_TO_PROVIDERS = """
INSERT INTO provider_model (provider, default_model, fast_model, updated_at)
SELECT provider, default_model, fast_model, updated_at FROM preference
WHERE default_model IS NOT NULL OR fast_model IS NOT NULL
"""
COPY_BACK = """
UPDATE preference SET
    default_model = (SELECT default_model FROM provider_model WHERE provider_model.provider = preference.provider),
    fast_model = (SELECT fast_model FROM provider_model WHERE provider_model.provider = preference.provider)
"""


def upgrade() -> None:
    op.create_table(
        "provider_model",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("default_model", sa.Text(), nullable=True),
        sa.Column("fast_model", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )
    op.execute(COPY_TO_PROVIDERS)

    with op.batch_alter_table("preference") as batch:
        for column in MODEL_COLUMNS:
            batch.drop_column(column)


def downgrade() -> None:
    with op.batch_alter_table("preference") as batch:
        for column in MODEL_COLUMNS:
            batch.add_column(sa.Column(column, sa.Text(), nullable=True))

    op.execute(COPY_BACK)
    op.drop_table("provider_model")
