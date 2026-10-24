from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from ov.agent.instances import access
from ov.agent.instances.http import open_client
from ov.agent.instances.ovproc import instances
from ov.agent.tools.base import Tool, ToolContext, ToolError, brief, clip, string_param
from ov.agent.tools.onevizion import INSTANCE, alias_for, target_instance, with_sign_in
from ov.core.paths import agent_dir, slugify

SCHEMA_PATH = "/v3/schema/db/{group}"
GROUPS = {
    "table": "tables",
    "view": "views",
    "type": "types",
    "package_spec": "package_specs",
    "package_body": "package_bodies",
}
SUFFIXES = ("", "_spec", "_body")
MAX_HITS = 60
HIT_CHARS = 200
NO_DDL = (
    "Your account on {instance} cannot download the platform DB source: it needs an AI Enabled instance with the "
    "METADATA and DB_DOCS privileges. Use ov_sql on all_tab_columns and all_source, or ov_export, instead."
)


def offered() -> list[Tool]:
    return TOOLS if any(access.allows(row["alias"], "dbSource") for row in instances()) else []


def _archive(alias: str, group: str) -> Path:
    version = (access.load(alias) or {}).get("version") or alias
    path = agent_dir("ddl", slugify(version)) / f"{group}.zip"
    if path.is_file():
        return path

    with open_client(alias) as client:
        content = client.api("GET", SCHEMA_PATH.format(group=group), accept="application/octet-stream").content
    partial = path.with_suffix(".part")
    partial.write_bytes(content)
    partial.replace(path)
    return path


def _groups(kind: str) -> list[str]:
    if not kind:
        return list(GROUPS.values())
    if kind not in GROUPS:
        raise ToolError(f"kind must be one of: {', '.join(GROUPS)}.")
    return [GROUPS[kind]]


def _named(alias: str, groups: list[str], name: str) -> str:
    wanted = {f"{name.lower()}{suffix}.sql" for suffix in SUFFIXES}
    found = []
    for group in groups:
        with zipfile.ZipFile(_archive(alias, group)) as archive:
            found += [
                f"-- {group}/{entry}\n{archive.read(entry).decode('utf-8', 'replace')}"
                for entry in archive.namelist()
                if entry.lower() in wanted
            ]

    if not found:
        raise ToolError(f"No {name} in the platform DB source. Search for it with find.")
    return "\n\n".join(found)


def _hits(alias: str, groups: list[str], text: str) -> str:
    pattern = re.compile(re.escape(text), re.IGNORECASE)
    hits: list[str] = []
    for group in groups:
        with zipfile.ZipFile(_archive(alias, group)) as archive:
            for entry in archive.namelist():
                lines = archive.read(entry).decode("utf-8", "replace").split("\n")
                hits += [
                    f"{group}/{entry}:{number}: {line.strip()[:HIT_CHARS]}"
                    for number, line in enumerate(lines, 1)
                    if pattern.search(line)
                ]
                if len(hits) >= MAX_HITS:
                    return "\n".join(hits[:MAX_HITS]) + f"\n(first {MAX_HITS} matches)"

    return "\n".join(hits) or f"No line in the platform DB source mentions {text!r}."


def _ddl(args: dict[str, Any], ctx: ToolContext) -> str:
    signed_in = alias_for(target_instance(args.get("instance"), ctx), ctx)
    alias = signed_in[0]
    if access.allows(alias, "dbSource") is False:
        raise ToolError(NO_DDL.format(instance=alias))

    groups = _groups(str(args.get("kind") or ""))
    name, text = str(args.get("name") or "").strip(), str(args.get("find") or "").strip()
    if bool(name) == bool(text):
        raise ToolError("Give either name or find.")

    if name:
        return clip(with_sign_in(signed_in, ctx, lambda a: _named(a, groups, name)), ctx, "DDL")
    return clip(with_sign_in(signed_in, ctx, lambda a: _hits(a, groups, text)), ctx, "matches")


TOOLS = [
    Tool(
        "ov_ddl",
        "Read the platform's own database source on AI Enabled instances, without Test SQL: the DDL of core tables, "
        "views and types, and package specs and bodies (UTIL and the other platform packages). Give name for one "
        "object's full DDL, or find to search every file for a word such as a column or procedure name. Instance "
        "configuration (rules, custom DB packages) is not in it; use ov_export for those.",
        {
            "instance": INSTANCE,
            "name": string_param("Object name, e.g. XITOR, CONFIG_FIELD or UTIL"),
            "find": string_param("Text to find in all files, e.g. SetValNumByID"),
            "kind": {"type": "string", "enum": list(GROUPS), "description": "Only look in this kind of object"},
        },
        [],
        lambda a: brief(f"ddl {a.get('name') or 'find ' + str(a.get('find'))}"),
        _ddl,
    ),
]
