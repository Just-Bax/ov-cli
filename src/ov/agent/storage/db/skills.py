from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert

from ov.agent.storage.db.clock import now_ms
from ov.agent.storage.db.engine import _begin
from ov.agent.storage.models import Skill, SkillSource

SKILL_FIELDS = ("title", "description", "content", "enabled")


def skill_rows() -> dict[str, dict[str, Any]]:
    with _begin() as conn:
        rows = conn.execute(select(*Skill.__table__.columns).order_by(Skill.name)).mappings().all()
    return {row["name"]: {**row, "enabled": bool(row["enabled"])} for row in rows}


def sync_bundled(skills: list[dict[str, str]]) -> None:
    now = now_ms()
    names = [skill["name"] for skill in skills]

    with _begin() as conn:
        conn.execute(delete(Skill).where(Skill.source == SkillSource.BUNDLED, Skill.name.not_in(names)))

        for skill in skills:
            text = {k: skill[k] for k in ("title", "description", "content")}
            statement = insert(Skill).values(
                name=skill["name"], source=SkillSource.BUNDLED, enabled=True, created_at=now, updated_at=now, **text
            )
            conn.execute(
                statement.on_conflict_do_update(
                    index_elements=[Skill.name], set_=text, where=Skill.source == SkillSource.BUNDLED
                )
            )


def add_skill(name: str, title: str, description: str, content: str) -> None:
    now = now_ms()
    values = {"title": title, "description": description, "content": content}

    with _begin() as conn:
        conn.execute(
            insert(Skill).values(
                name=name, source=SkillSource.CUSTOM, enabled=True, created_at=now, updated_at=now, **values
            )
        )


def update_skill(name: str, **fields: Any) -> None:
    unknown = set(fields) - set(SKILL_FIELDS)
    if unknown:
        raise ValueError(f"Skills have no {', '.join(sorted(unknown))}.")
    with _begin() as conn:
        conn.execute(update(Skill).where(Skill.name == name).values(updated_at=now_ms(), **fields))


def delete_skill(name: str) -> None:
    with _begin() as conn:
        conn.execute(delete(Skill).where(Skill.name == name, Skill.source == SkillSource.CUSTOM))
