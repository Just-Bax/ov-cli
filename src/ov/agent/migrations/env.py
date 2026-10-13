from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from ov.agent.models import Base
from ov.paths import agent_dir


def _migrate(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    _migrate(connection)
else:
    with create_engine(f"sqlite:///{agent_dir() / 'agent.db'}").connect() as cli_connection:
        _migrate(cli_connection)
