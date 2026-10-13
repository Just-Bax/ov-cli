from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

LEGACY_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, title TEXT NOT NULL, instance TEXT, "
    "status TEXT NOT NULL, model TEXT NOT NULL, input TEXT NOT NULL, "
    "saved_minutes INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, seq INTEGER NOT NULL, ts INTEGER NOT NULL, "
    "data TEXT NOT NULL, PRIMARY KEY (run_id, seq))",
    "CREATE TABLE IF NOT EXISTS conversation (run_id TEXT PRIMARY KEY, messages TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS settled (run_id TEXT PRIMARY KEY, ts INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS pinned (run_id TEXT PRIMARY KEY, ts INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS snoozed (run_id TEXT PRIMARY KEY, until INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS feedback (run_id TEXT PRIMARY KEY, rating TEXT NOT NULL, note TEXT NOT NULL, "
    "ts INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS usage (run_id TEXT NOT NULL, ts INTEGER NOT NULL, model TEXT NOT NULL, "
    "kind TEXT NOT NULL, tokens TEXT NOT NULL, nano INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS usage_by_run ON usage (run_id)",
    "CREATE INDEX IF NOT EXISTS usage_by_time ON usage (ts)",
    "CREATE TABLE IF NOT EXISTS skills (name TEXT PRIMARY KEY, title TEXT, description TEXT, content TEXT, "
    "enabled INTEGER NOT NULL DEFAULT 1)",
)


def upgrade() -> None:
    for statement in LEGACY_SCHEMA:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("The baseline schema cannot be downgraded.")
