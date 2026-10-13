from __future__ import annotations

import re
import threading
from typing import Any

from ov.agent import workspace as project
from ov.agent.tools.base import (
    LABEL_CHARS,
    Handler,
    Tool,
    ToolContext,
    ToolError,
    approved,
    clip,
    int_param,
    raising_tool_errors,
    string_param,
)

_NO_OP_COMMAND = re.compile(r"^(echo|write-host|write-output)\b[^|;&>]*$|^\s*$", re.IGNORECASE)

_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _workspace(handler: Handler) -> Handler:
    return raising_tool_errors(handler, project.ProjectError, ValueError)


def _ws_list(args: dict[str, Any], ctx: ToolContext) -> str:
    return clip(project.listing(str(args.get("path") or ""), str(args.get("glob") or "")), ctx, "listing")


def _ws_search(args: dict[str, Any], ctx: ToolContext) -> str:
    found = project.search(
        str(args["pattern"]),
        str(args.get("path") or ""),
        str(args.get("glob") or ""),
        bool(args.get("ignore_case")),
    )
    return clip(found, ctx, "search")


def _ws_read(args: dict[str, Any], ctx: ToolContext) -> str:
    end = int(args["end"]) if args.get("end") else None
    return clip(project.read(str(args["path"]), int(args.get("start") or 1), end), ctx, "file")


def _file_lock(rel: str) -> threading.Lock:
    key = str(project.resolve(rel)).lower()
    with _file_locks_guard:
        return _file_locks.setdefault(key, threading.Lock())


def _ws_edit(args: dict[str, Any], ctx: ToolContext) -> str:
    path, old, new = str(args["path"]), str(args["old"]), str(args["new"])
    with _file_lock(path):
        result = project.edit(path, old, new, bool(args.get("replace_all")))
    ctx.record_edit(path, old, new, created=False)
    return result


def _ws_write(args: dict[str, Any], ctx: ToolContext) -> str:
    path, content = str(args["path"]), str(args["content"])
    with _file_lock(path):
        existed = project.resolve(path).is_file()
        before = project.text_of(path) if existed else ""
        result = project.write(path, content)
    ctx.record_edit(path, before, content, created=not existed)
    return result


def _ws_run(args: dict[str, Any], ctx: ToolContext) -> str:
    command = str(args["command"]).strip()
    if _NO_OP_COMMAND.match(command):
        raise ToolError("Nothing to run. To just answer, reply without a tool call.")
    folder = str(args.get("cwd") or "")
    risky = project.risks(command, project.resolve(folder))
    if risky:
        where = folder or "the workspace root"
        if not approved(ctx, f"Run this command? It {', and '.join(risky)}.", f"{where}> {command}"):
            raise ToolError("The user rejected this command. Do not retry it; ask what they want instead.")

    timeout = int(args.get("timeout") or project.DEFAULT_TIMEOUT_SECONDS)
    return clip(project.run(command, folder, timeout, ctx.cancel), ctx, "command output")


TOOLS = [
    Tool(
        "ws_list",
        "List a folder in the workspace, or with glob every file matching a glob such as "
        '"**/*.py" or "pom.xml". Skips .git, node_modules, build output.',
        {
            "path": string_param("Folder relative to the workspace root; default the root"),
            "glob": string_param("Optional glob"),
        },
        [],
        lambda a: f"list {a.get('path') or '.'}{' ' + str(a['glob']) if a.get('glob') else ''}",
        _workspace(_ws_list),
    ),
    Tool(
        "ws_search",
        "Search file contents in the workspace with a regex. Returns path:line: text.",
        {
            "pattern": string_param("Regex"),
            "path": string_param("Folder to search, relative to the workspace root; default the root"),
            "glob": string_param('Only files matching this glob, e.g. "*.sql"'),
            "ignore_case": {"type": "boolean"},
        },
        ["pattern"],
        lambda a: f"search {a.get('path') or '.'}: {a.get('pattern')}",
        _workspace(_ws_search),
    ),
    Tool(
        "ws_read",
        f"Read a text file in the workspace with line numbers, up to {project.MAX_READ_LINES} lines per call.",
        {
            "path": string_param("File path relative to the workspace root"),
            "start": int_param("First line"),
            "end": int_param("Last line"),
        },
        ["path"],
        lambda a: f"read {a.get('path')}",
        _workspace(_ws_read),
    ),
    Tool(
        "ws_edit",
        "Edit a workspace file by replacing exact text. old must match the file exactly, including "
        "indentation, and be unique unless replace_all is set. Read the file first.",
        {
            "path": string_param("File path relative to the workspace root"),
            "old": string_param("Exact text to replace"),
            "new": string_param("Replacement text"),
            "replace_all": {"type": "boolean"},
        },
        ["path", "old", "new"],
        lambda a: f"edit {a.get('path')}",
        _workspace(_ws_edit),
    ),
    Tool(
        "ws_write",
        "Create a workspace file, or overwrite it completely. Prefer ws_edit for changes to existing files.",
        {
            "path": string_param("File path relative to the workspace root"),
            "content": string_param("Full file content"),
        },
        ["path", "content"],
        lambda a: f"write {a.get('path')}",
        _workspace(_ws_write),
    ),
    Tool(
        "ws_run",
        "Run a shell command (PowerShell on Windows, bash elsewhere) in a workspace folder: git, "
        "builds, tests, scripts. Deleting files, git push, history rewrites and anything outside the "
        "workspace wait for the user's approval.",
        {
            "command": string_param("The command line"),
            "cwd": string_param("Folder relative to the workspace root; default the root"),
            "timeout": int_param(
                f"Seconds, default {project.DEFAULT_TIMEOUT_SECONDS}, max {project.MAX_TIMEOUT_SECONDS}"
            ),
        },
        ["command"],
        lambda a: f"$ {a.get('command')}"[:LABEL_CHARS],
        _workspace(_ws_run),
    ),
]


def offered() -> list[Tool]:
    return TOOLS if project.configured() else []
