from __future__ import annotations

import re
import threading
from typing import Any

from ov.agent import workspace as project
from ov.agent.engine.guard import Effect
from ov.agent.tools.base import (
    UI_ONLY,
    Handler,
    Tool,
    ToolContext,
    ToolError,
    approved,
    brief,
    clip,
    int_param,
    mask_secrets,
    raising_tool_errors,
    string_param,
)

_NO_OP_COMMAND = re.compile(r"^(echo|write-host|write-output)\b[^|;&>]*$|^\s*$", re.IGNORECASE)
EDITS_OFF = (
    "Not changed: this thread is Read-only. Show the user the change you would make and why; they "
    "can switch the thread from Read-only to Ask first or Auto below the chat."
)
COMMAND_OFF = (
    "Not run: {reason}. It changes something and this thread is Read-only. Tell the user what you "
    "would run and why; they can switch the thread from Read-only to Ask first or Auto below the chat."
)

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


def _require_write(ctx: ToolContext) -> None:
    if not ctx.can_write():
        raise ToolError(EDITS_OFF)


def _ws_edit(args: dict[str, Any], ctx: ToolContext) -> str:
    _require_write(ctx)

    path, old, new = str(args["path"]), str(args["old"]), str(args["new"])
    with _file_lock(path):
        before = project.text_of(path)
        result = project.edit(path, old, new, bool(args.get("replace_all")))
        after = project.text_of(path)

    ctx.record_edit(path, before, after, created=False)
    return result


def _ws_write(args: dict[str, Any], ctx: ToolContext) -> str:
    _require_write(ctx)

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
    timeout = int(args.get("timeout") or project.DEFAULT_TIMEOUT_SECONDS)
    if ctx.full_access() and not ctx.browser.live:
        return clip(project.run(command, folder, timeout, ctx.cancel), ctx, "command output")

    cwd = project.resolve(folder)
    escapes = project.escapes(command, cwd, (ctx.work_dir,))
    scripts = {path: mask_secrets(text) for path, text in project.scripts_run(command, cwd).items()}
    verdict = ctx.judge_command(command, folder, scripts)
    if verdict.effect != Effect.READ and not ctx.can_write():
        raise ToolError(COMMAND_OFF.format(reason=verdict.reason))

    if verdict.effect != Effect.READ and ctx.browser.live:
        raise ToolError(UI_ONLY)

    asks_first = verdict.effect != Effect.READ and not ctx.auto_approves()
    if verdict.effect == Effect.OUTSIDE or escapes or asks_first:
        reasons = "; ".join([verdict.reason, *escapes])
        where = folder or "the workspace root"
        if not approved(ctx, f"Run this command? {reasons}.", f"{where}> {command}"):
            raise ToolError("The user rejected this command. Do not retry it; ask what they want instead.")

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
        "Edit a workspace file by replacing exact text; needs changes allowed. old must match the file exactly, "
        "including indentation, and be unique unless replace_all is set. Read the file first.",
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
        "Create a workspace file, or overwrite it completely. Prefer ws_edit for changes to existing files. "
        "Needs changes allowed.",
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
        "builds, tests, scripts. Each command is judged first: commands that only read always run; "
        "commands that change anything need changes allowed; pushes, remote writes, deletes, unknown scripts "
        "and paths outside the workspace also wait for the user's approval (in Auto only when risky).",
        {
            "command": string_param("The command line"),
            "cwd": string_param("Folder relative to the workspace root; default the root"),
            "timeout": int_param(
                f"Seconds, default {project.DEFAULT_TIMEOUT_SECONDS}, max {project.MAX_TIMEOUT_SECONDS}"
            ),
        },
        ["command"],
        lambda a: brief(f"$ {a.get('command')}"),
        _workspace(_ws_run),
    ),
]


def offered() -> list[Tool]:
    return TOOLS if project.configured() else []
