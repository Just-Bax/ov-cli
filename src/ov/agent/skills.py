from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import db

BUILTIN_DIR = Path(__file__).parent / "skills"

# The order skills appear in the system prompt.
ORDER = (
    "onevizion",
    "working-style",
    "ov-cli",
    "sources",
    "github",
    "datadog",
    "tce-best-practices",
)

_FRONT_MATTER = re.compile(r"^---\n([\s\S]*?)\n---\n?([\s\S]*)$")
_SLUG = re.compile(r"[^a-z0-9]+")


class SkillError(Exception):
    pass


def _parse(name: str, raw: str) -> dict[str, str]:
    match = _FRONT_MATTER.match(raw.replace("\r\n", "\n"))
    meta: dict[str, str] = {}
    for line in (match.group(1) if match else "").split("\n"):
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return {
        "name": name,
        "title": meta.get("title", name),
        "description": meta.get("description", ""),
        "content": (match.group(2) if match else raw).strip(),
    }


def builtins() -> list[dict[str, str]]:
    found = [_parse(p.stem, p.read_text(encoding="utf-8")) for p in BUILTIN_DIR.glob("*.md")]

    def rank(skill: dict[str, str]) -> tuple[int, str]:
        name = skill["name"]
        return (ORDER.index(name) if name in ORDER else len(ORDER), name)

    return sorted(found, key=rank)


def list_skills() -> list[dict[str, Any]]:
    rows = db.skill_rows()
    skills = []
    for builtin in builtins():
        row = rows.pop(builtin["name"], None) or {}
        customized = row.get("content") is not None
        skills.append(
            {
                **builtin,
                "content": row["content"] if customized else builtin["content"],
                "builtin": True,
                "customized": customized,
                "enabled": bool(row.get("enabled", 1)),
            }
        )
    for name, row in sorted(rows.items()):
        skills.append(
            {
                "name": name,
                "title": row.get("title") or name,
                "description": row.get("description") or "",
                "content": row.get("content") or "",
                "builtin": False,
                "customized": False,
                "enabled": bool(row.get("enabled", 1)),
            }
        )
    return skills


def enabled_skills() -> list[dict[str, Any]]:
    return [s for s in list_skills() if s["enabled"] and s["content"].strip()]


def create(title: str, description: str, content: str) -> str:
    title = title.strip()
    if not title:
        raise SkillError("A skill needs a title.")
    taken = {s["name"] for s in list_skills()}
    base = _SLUG.sub("-", title.lower()).strip("-") or "skill"
    name, index = base, 2
    while name in taken:
        name, index = f"{base}-{index}", index + 1
    db.put_skill(
        name, title=title, description=description.strip(), content=content.strip(), enabled=1
    )
    return name


def update(name: str, patch: dict[str, Any]) -> None:
    skill = next((s for s in list_skills() if s["name"] == name), None)
    if skill is None:
        raise SkillError(f"Unknown skill: {name}")

    fields: dict[str, Any] = {}
    if "content" in patch:
        fields["content"] = str(patch["content"]).strip()
    if "enabled" in patch:
        fields["enabled"] = 1 if patch["enabled"] else 0
    if not skill["builtin"]:
        for key in ("title", "description"):
            if key in patch:
                fields[key] = str(patch[key]).strip()
    db.put_skill(name, **fields)


# Deleting a built-in skill resets it to the shipped text instead.
def delete(name: str) -> None:
    db.delete_skill(name)
