from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, unquote

from ov.agent import skills
from ov.agent.engine.run_common import RunError

MENTION = re.compile(r"\[([^\[\]\n]+)\]\((attachment|workspace|ov|thread|skill):([^()\s]+)\)")


def _encoded(target: str) -> str:
    return quote(target, safe="/")


def renames(files: list[dict[str, str]], uploaded: list[dict[str, Any]]) -> dict[str, str]:
    return {str(sent["name"]): stored["name"] for sent, stored in zip(files, uploaded, strict=True)}


def relink(text: str, renamed: dict[str, str]) -> str:
    def swap(match: re.Match[str]) -> str:
        if match.group(2) != "attachment":
            return match.group(0)

        stored = renamed.get(unquote(match.group(3)))
        if stored is None:
            return match.group(0)

        return f"[{stored}](attachment:{_encoded(stored)})"

    return MENTION.sub(swap, text)


def _skill_names(text: str) -> list[str]:
    found = [unquote(m.group(3)) for m in MENTION.finditer(text) if m.group(2) == "skill"]
    return list(dict.fromkeys(found))


def with_skills(text: str) -> str:
    names = _skill_names(text)
    if not names:
        return text

    known = {s["name"]: s for s in skills.list_skills()}
    missing = [name for name in names if name not in known]
    if missing:
        raise RunError(f"Unknown skill: {', '.join(missing)}. It may have been deleted; pick it again.")

    blocks = [
        f'<skill name="{name}" title="{known[name]["title"]}">\n{known[name]["content"]}\n</skill>' for name in names
    ]
    return text + "\n\nSkills the user picked for this message:\n\n" + "\n\n".join(blocks)
