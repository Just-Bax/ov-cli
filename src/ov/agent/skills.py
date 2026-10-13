from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import db
from .models import SkillSource

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


def bundled() -> list[dict[str, Any]]:
    found = [_parse(p.stem, p.read_text(encoding="utf-8")) for p in BUILTIN_DIR.glob("*.md")]
    return sorted(found, key=lambda skill: ORDER.index(skill["name"]))


def list_skills() -> list[dict[str, Any]]:
    shipped = bundled()
    db.sync_bundled(shipped)
    core = {skill["name"] for skill in shipped if skill["core"]}
    order = {skill["name"]: index for index, skill in enumerate(shipped)}
    rows = sorted(
        db.skill_rows().values(),
        key=lambda row: (row["source"] != SkillSource.BUNDLED, order.get(row["name"], 0), row["name"]),
    )
    return [
        {
            "name": row["name"],
            "source": row["source"],
            "title": row["title"],
            "description": row["description"],
            "content": row["content"],
            "core": row["name"] in core,
            "enabled": row["enabled"],
        }
        for row in rows
    ]


REPLY_SKILL = "tce-best-practices"
REPLY_HEADING = "## Reply style"


def reply_style() -> str:
    enabled = [s for s in list_skills() if s["enabled"]]
    preferred = [s for s in enabled if s["source"] == SkillSource.CUSTOM] + [
        s for s in enabled if s["source"] != SkillSource.CUSTOM
    ]
    skill = next((s for s in preferred if REPLY_HEADING in s["content"]), None)
    if skill is None:
        raise SkillError(f'No enabled skill has a "{REPLY_HEADING[3:]}" section; turn on {REPLY_SKILL}.')
    content = skill["content"]
    start = content.find(REPLY_HEADING)
    end = content.find("\n## ", start + len(REPLY_HEADING))
    return content[start : end if end > 0 else len(content)].strip()


def enabled_skills() -> list[dict[str, Any]]:
    return [s for s in list_skills() if s["enabled"] and s["content"].strip()]


def _free_name(title: str) -> str:
    taken = {s["name"] for s in list_skills()}
    base = _SLUG.sub("-", title.lower()).strip("-") or "skill"
    name, index = base, 2
    while name in taken:
        name, index = f"{base}-{index}", index + 1
    return name


def create(title: str, description: str, content: str) -> str:
    title = title.strip()
    if not title:
        raise SkillError("A skill needs a title.")

    name = _free_name(title)
    db.add_skill(name, title, description.strip(), content.strip())
    return name


def _find(name: str) -> dict[str, Any]:
    skill = next((s for s in list_skills() if s["name"] == name), None)
    if skill is None:
        raise SkillError(f"Unknown skill: {name}")
    return skill


def clone(name: str) -> str:
    source = _find(name)
    title = f"{source['title']} (copy)"
    copy = _free_name(title)
    db.add_skill(copy, title, source["description"], source["content"])
    if source["source"] == SkillSource.BUNDLED:
        db.update_skill(name, enabled=False)
    return copy


def update(name: str, patch: dict[str, Any]) -> None:
    skill = _find(name)
    fields: dict[str, Any] = {}
    if "enabled" in patch:
        fields["enabled"] = bool(patch["enabled"])
    editable = {key: str(patch[key]).strip() for key in ("title", "description", "content") if key in patch}
    if editable and skill["source"] == SkillSource.BUNDLED:
        raise SkillError(f"{skill['title']} ships with ov and cannot be edited. Clone it and edit the copy.")
    if "title" in editable and not editable["title"]:
        raise SkillError("A skill needs a title.")
    db.update_skill(name, **fields, **editable)


def delete(name: str) -> None:
    skill = _find(name)
    if skill["source"] == SkillSource.BUNDLED:
        raise SkillError(f"{skill['title']} ships with ov and cannot be deleted. Turn it off instead.")
    db.delete_skill(name)
