from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import db

BUILTIN_DIR = Path(__file__).parent / "skills"

ORDER = (
    "onevizion",
    "working-style",
    "ov-cli",
    "workspace",
    "datadog",
    "pagerduty",
    "tce-best-practices",
)

_FRONT_MATTER = re.compile(r"^---\n([\s\S]*?)\n---\n?([\s\S]*)$")
_SLUG = re.compile(r"[^a-z0-9]+")


class SkillError(Exception):
    pass


def _parse(name: str, raw: str) -> dict[str, Any]:
    match = _FRONT_MATTER.match(raw.replace("\r\n", "\n"))
    if match is None:
        raise SkillError(f"Built-in skill {name} has no front matter.")

    meta: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    if "title" not in meta or "description" not in meta:
        raise SkillError(f"Built-in skill {name} needs a title and a description.")

    return {
        "name": name,
        "title": meta["title"],
        "description": meta["description"],
        "core": meta.get("core") == "true",
        "content": match.group(2).strip(),
    }


def builtins() -> list[dict[str, Any]]:
    found = [_parse(p.stem, p.read_text(encoding="utf-8")) for p in BUILTIN_DIR.glob("*.md")]
    return sorted(found, key=lambda skill: ORDER.index(skill["name"]))


def _builtin_entry(builtin: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {**builtin, "builtin": True, "customized": False, "enabled": True}

    customized = row["content"] is not None
    return {
        **builtin,
        "content": row["content"] if customized else builtin["content"],
        "builtin": True,
        "customized": customized,
        "enabled": bool(row["enabled"]),
    }


def list_skills() -> list[dict[str, Any]]:
    rows = db.skill_rows()
    skills = [_builtin_entry(builtin, rows.pop(builtin["name"], None)) for builtin in builtins()]
    skills += [
        {
            "name": name,
            "title": row["title"],
            "description": row["description"],
            "content": row["content"],
            "core": False,
            "builtin": False,
            "customized": False,
            "enabled": bool(row["enabled"]),
        }
        for name, row in sorted(rows.items())
    ]
    return skills


REPLY_SKILL = "tce-best-practices"
REPLY_HEADING = "## Reply style"


def reply_style() -> str:
    skill = next((s for s in list_skills() if s["name"] == REPLY_SKILL), None)
    if skill is None:
        raise SkillError(f"The {REPLY_SKILL} skill is missing, and it holds the reply style.")
    content = skill["content"]
    start = content.find(REPLY_HEADING)
    if start < 0:
        raise SkillError(f'The {skill["title"]} skill has no "{REPLY_HEADING[3:]}" section.')
    end = content.find("\n## ", start + len(REPLY_HEADING))
    return content[start : end if end > 0 else len(content)].strip()


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
    db.put_skill(name, title=title, description=description.strip(), content=content.strip(), enabled=1)
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
        fields.update({key: str(patch[key]).strip() for key in ("title", "description") if key in patch})
    db.put_skill(name, **fields)


def delete(name: str) -> None:
    db.delete_skill(name)
