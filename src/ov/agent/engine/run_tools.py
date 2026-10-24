from __future__ import annotations

import difflib
import json
from typing import Any

from ov.agent.engine.run_common import RunError, uid
from ov.agent.engine.tasks import Task, TaskContext
from ov.agent.storage import db
from ov.agent.tools import tool_named
from ov.agent.tools.base import Tool, ToolError

MAX_BACKGROUND_TASKS = 8
TOOL_INPUT_CHARS = 8000
TOOL_OUTPUT_CHARS = 12000
TOOL_ERROR_CHARS = 4000
BAD_ARGS_CHARS = 200
EDIT_CHARS = 60_000
BACKGROUND_STARTED = (
    "Running in the background as {label}. Its result arrives as a message when it finishes. Continue with "
    "checks that do not depend on it, or end your turn and you will be woken with the result. Do not guess "
    "its result."
)
BACKGROUND_FULL = "{count} tasks already run in the background. Wait for one to finish first."
TASK_STOPPED_NOTE = "The user stopped the background task {label}; it gave no result."
STOPPED_BY_USER = "Stopped by the user."
CUT_OFF_ARGUMENTS = (
    "the arguments of this call were cut off or were not valid JSON, so it did not run. This "
    "usually means the content was too long for one reply. Do not resend it in one piece: write a "
    "large file in parts (ws_write a short first part, then add the rest with ws_edit), or shorten it."
)


class ToolsMixin:
    def _stop_tasks(self) -> None:
        with self._lock:
            live = list(self._tasks.values())
        for task in live:
            self._stop_task(task)

    def _stop_task(self, task: Task) -> None:
        with self._lock:
            if task.finished or task.stopped_at is not None:
                return
            task.stopped_at = db.now_ms()
        task.cancel.set()
        self.emit({"type": "tool", "tool": {"id": task.id, "stoppedAt": task.stopped_at}})

    def stop_tool(self, tool_id: str) -> None:
        with self._lock:
            task = self._tasks.get(tool_id)
        if task is None:
            raise RunError("That tool is no longer running.")

        self._stop_task(task)
        if task.backgrounded_at is not None:
            self._notes.append(TASK_STOPPED_NOTE.format(label=task.label))

    def move_to_background(self, tool_id: str) -> None:
        with self._lock:
            task = self._tasks.get(tool_id)
            if task is None or task.finished:
                raise RunError("That tool is no longer running.")
            if task.backgrounded_at is not None:
                return
            if self._questions or self._logins:
                raise RunError("Answer the open question first.")
            self._check_background_room()
            task.backgrounded_at = db.now_ms()
        self.emit({"type": "tool", "tool": {"id": task.id, "backgroundedAt": task.backgrounded_at}})
        task.settled.set()

    def _check_background_room(self) -> None:
        count = len(self._background_tasks())
        if count >= MAX_BACKGROUND_TASKS:
            raise RunError(BACKGROUND_FULL.format(count=count))

    def record_edit(self, path: str, before: str, after: str, created: bool) -> None:
        added, removed = _line_changes(before, after)
        truncated = len(before) > EDIT_CHARS or len(after) > EDIT_CHARS
        edit = {
            "id": uid("e"),
            "toolId": getattr(self._local, "tool", ""),
            "path": path.replace("\\", "/"),
            "created": created,
            "added": added,
            "removed": removed,
            "before": before[:EDIT_CHARS],
            "after": after[:EDIT_CHARS],
            "truncated": truncated,
        }

        self.emit({"type": "edit", "edit": edit})

    def attach_image(self, name: str, url: str) -> None:
        self._pending_images.append((name, url))

    def take_images(self) -> list[tuple[str, str]]:
        with self._lock:
            images, self._pending_images = self._pending_images, []
        return images

    def call_tool_named(self, name: str, args: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
        call = {"id": uid("c"), "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        output = self.call_tool(call)
        return output, self.take_images()

    def call_tool(self, call: dict[str, Any]) -> str:
        if self.cancel.is_set():
            return STOPPED_BY_USER

        self._local.tool = call["id"]
        try:
            tool, args = self._parsed_call(call)
        except ToolError as exc:
            return f"Error: {exc}"
        if tool.silent:
            return self._call_silent(tool, args)

        try:
            task = self._start_task(call["id"], tool, args)
        except RunError as exc:
            return f"Error: {exc}"

        task.settled.wait()
        with self._lock:
            if task.backgrounded_at is not None:
                return BACKGROUND_STARTED.format(label=task.label)
            return task.result

    def _parsed_call(self, call: dict[str, Any]) -> tuple[Tool, dict[str, Any]]:
        if call["id"] in self._cut_off:
            raise ToolError(CUT_OFF_ARGUMENTS)

        name = call["function"]["name"]
        tool = tool_named(name)
        if tool is None:
            raise ToolError(f"unknown tool {name}")
        return tool, _tool_args(tool, call["function"]["arguments"])

    def _call_silent(self, tool: Tool, args: dict[str, Any]) -> str:
        try:
            return tool.handler(args, self)
        except Exception as exc:
            return f"Error: {str(exc) or type(exc).__name__}"

    def _start_task(self, call_id: str, tool: Tool, args: dict[str, Any]) -> Task:
        background = args.pop("background", False) is True
        base = {
            "id": call_id,
            "name": tool.name,
            "label": tool.label(args),
            "input": json.dumps(args, indent=2)[:TOOL_INPUT_CHARS],
        }
        task = Task(base, db.now_ms())

        with self._lock:
            if background:
                self._check_background_room()
                task.backgrounded_at = task.started_at
                task.settled.set()
            self._tasks[task.id] = task

        running = {**base, "status": "running", "startedAt": task.started_at}
        if task.backgrounded_at is not None:
            running["backgroundedAt"] = task.backgrounded_at

        self.emit({"type": "tool", "tool": running})
        self._spawn(self._work, tool, args, task)
        return task

    def _work(self, tool: Tool, args: dict[str, Any], task: Task) -> None:
        self._local.tool = task.id
        try:
            output = tool.handler(args, TaskContext(self, task))
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            self._finish_task(task, "error", message, f"Error: {message}")
            return
        self._finish_task(task, "ok", output, output)

    def _finish_task(self, task: Task, status: str, output: str, result: str) -> None:
        if task.stopped_at is not None:
            status, output, result = "error", STOPPED_BY_USER, f"Error: {STOPPED_BY_USER}"
        limit = TOOL_OUTPUT_CHARS if status == "ok" else TOOL_ERROR_CHARS
        done = {**task.tool, "status": status, "ms": db.now_ms() - task.started_at, "output": output[:limit]}
        if task.stopped_at is not None:
            done["stoppedAt"] = task.stopped_at

        self.emit({"type": "tool", "tool": done})

        with self._lock:
            task.result, task.finished = result, True
            del self._tasks[task.id]
            deliver = task.backgrounded_at is not None and task.stopped_at is None
            if deliver:
                self._finished_tasks.append(task)

        task.settled.set()
        if deliver:
            self._pick_up_queue()
        else:
            self._settle_if_quiet()

    def _settle_if_quiet(self) -> None:
        with self._lock:
            quiet = not (self._busy or self._finished_tasks or self._background_tasks())
        if quiet and self.state["summary"]["status"] == "running":
            self._set_status("done")

    def _background_tasks(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.backgrounded_at is not None]

    def _background_live(self) -> bool:
        with self._lock:
            return bool(self._background_tasks())

    def _tool_done(self, base: dict[str, Any], status: str, started: int, output: str) -> None:
        tool = {**base, "status": status, "ms": db.now_ms() - started, "output": output}
        self.emit({"type": "tool", "tool": tool})


def _tool_args(tool: Tool, raw: str) -> dict[str, Any]:
    try:
        args = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise ToolError(f"arguments are not valid JSON: {raw[:BAD_ARGS_CHARS]}") from None

    if not isinstance(args, dict):
        raise ToolError("arguments must be a JSON object.")

    missing = [key for key in tool.required if key not in args]
    if missing:
        raise ToolError(f"missing required arguments: {', '.join(missing)}")
    return args


def _line_changes(before: str, after: str) -> tuple[int, int]:
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, before.splitlines(), after.splitlines(), autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            removed += i2 - i1
            added += j2 - j1
    return added, removed
