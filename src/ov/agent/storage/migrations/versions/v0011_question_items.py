from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

STOPPED_ANSWER = "(not answered: the run stopped)"
RISKY_NOTE = "\n\nAuto mode asks because this looks risky: "


def _closed(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    answer = old.get("answer")
    if answer == STOPPED_ANSWER:
        return {**new, "stopped": True}
    if answer is not None:
        return {**new, "answers": [answer]}
    return new


def _approval(old: dict[str, Any]) -> dict[str, Any]:
    detail, _, reason = str(old["detail"]).partition(RISKY_NOTE)
    new = {"id": old["id"], "kind": "approval", "question": old["question"], "detail": detail}
    if reason:
        new["reason"] = reason
    return new


def _ask(old: dict[str, Any]) -> dict[str, Any]:
    item = {
        "header": "",
        "question": old["question"],
        "options": [{"label": str(o)} for o in old.get("options") or []],
        "multiple": bool(old.get("multiple")),
    }
    return {"id": old["id"], "kind": "ask", "items": [item]}


def _converted(old: dict[str, Any]) -> dict[str, Any]:
    new = _approval(old) if old.get("detail") else _ask(old)
    if old.get("toolId"):
        new["toolId"] = old["toolId"]
    return _closed(old, new)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT thread_id, position, data FROM event WHERE type = 'question'")).fetchall()
    for thread_id, position, data in rows:
        event = json.loads(data)
        event["question"] = _converted(event["question"])
        conn.execute(
            sa.text("UPDATE event SET data = :data WHERE thread_id = :thread AND position = :position"),
            {"data": json.dumps(event), "thread": thread_id, "position": position},
        )


def downgrade() -> None:
    op.execute("DELETE FROM event WHERE type = 'question'")
