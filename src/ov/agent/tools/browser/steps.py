from __future__ import annotations

from typing import Any

from ov.agent.tools.base import Handler, Tool, ToolContext, ToolError, int_param, string_param
from ov.agent.tools.browser.page import dialog_note, result
from ov.agent.tools.browser.specs import (
    AIM,
    DEFAULT_WAIT_SECONDS,
    FILES,
    SAY,
    SCROLL_PIXELS,
    SCROLLS,
    SUBMIT_KEY,
    aimed,
    said,
)
from ov.browser.model import BrowserError, DialogOpen
from ov.browser.pilot import Pilot

MAX_STEPS = 12
AIMED_STEPS = frozenset({"click", "select", "hover", "upload"})
STEP_FIELDS = {
    "type": ("text",),
    "press": ("key",),
    "select": ("option",),
    "scroll": ("direction",),
    "upload": ("files",),
}

NO_STEPS = "Give at least one step."
TOO_MANY_STEPS = f"Give at most {MAX_STEPS} steps; split the rest into another browser_steps call."
UNKNOWN_STEP = "Step {number}: {action!r} is not a step; use one of {actions}."
STEP_NEEDS_AIM = "Step {number} ({action}) needs one of ref, locator, or x and y."
STEP_NEEDS = "Step {number} ({action}) needs {fields}."
STOPPED_AT = "Stopped at step {number} of {total}: {error}"
MOVED_ON = (
    "The page went to another address after step {number}, so the last {left} step(s) did not run. Take a snapshot "
    "and continue from there."
)

Actions = dict[str, Handler]


def _planned(args: dict[str, Any], actions: Actions) -> list[dict[str, Any]]:
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ToolError(NO_STEPS)
    if len(steps) > MAX_STEPS:
        raise ToolError(TOO_MANY_STEPS)

    planned = []
    for number, step in enumerate(steps, start=1):
        action = step.get("action") if isinstance(step, dict) else None
        if action not in actions:
            raise ToolError(UNKNOWN_STEP.format(number=number, action=action, actions=", ".join(actions)))
        if action in AIMED_STEPS and not aimed(step):
            raise ToolError(STEP_NEEDS_AIM.format(number=number, action=action))

        missing = [name for name in STEP_FIELDS.get(action, ()) if step.get(name) in (None, "", [])]
        if missing:
            raise ToolError(STEP_NEEDS.format(number=number, action=action, fields=", ".join(missing)))
        planned.append({**step, "say": str(step.get("say") or args["say"])})

    return planned


def _do_steps(steps: list[dict[str, Any]], actions: Actions, ctx: ToolContext, pilot: Pilot, done: list[str]) -> None:
    start = pilot.where()[1]
    for number, step in enumerate(steps, start=1):
        ctx.cancel.check()
        try:
            done.append(f"{number}. {actions[step['action']](step, ctx)}")
        except DialogOpen:
            raise
        except (ToolError, BrowserError) as exc:
            if not done:
                raise
            done.append(STOPPED_AT.format(number=number, total=len(steps), error=exc))
            return

        left = len(steps) - number
        if left and pilot.where()[1] != start:
            done.append(MOVED_ON.format(number=number, left=left))
            return


def _stepper(actions: Actions) -> Handler:
    def run(args: dict[str, Any], ctx: ToolContext) -> str:
        steps = _planned(args, actions)
        pilot = ctx.browser.pilot()
        done: list[str] = []
        try:
            _do_steps(steps, actions, ctx, pilot, done)
            return result(pilot, "\n".join(done))
        except DialogOpen as exc:
            return "\n".join([*done, dialog_note(exc)])

    return run


def _step_schema(actions: Actions) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(actions)},
            **AIM,
            "text": string_param("type: the text to type. wait: text that must appear"),
            "clear": {"type": "boolean", "description": "type: clear the field first"},
            "submit": {"type": "boolean", "description": f"type: press {SUBMIT_KEY} afterwards"},
            "double": {"type": "boolean", "description": "click: double-click"},
            "key": string_param("press: key as Playwright writes it"),
            "option": string_param("select: visible text of the option"),
            "direction": {"type": "string", "enum": list(SCROLLS), "description": "scroll: direction"},
            "pixels": int_param(f"scroll: how far, default {SCROLL_PIXELS}"),
            "url_contains": string_param("wait: part the URL must contain"),
            "seconds": int_param(f"wait: longest wait, default {DEFAULT_WAIT_SECONDS}"),
            "files": FILES,
            "say": string_param("What the user sees for this step; defaults to the say of the call"),
        },
        "required": ["action"],
        "additionalProperties": False,
    }


def steps_tool(actions: Actions) -> Tool:
    return Tool(
        "browser_steps",
        f"Do up to {MAX_STEPS} actions in a row in one call, when you already know them from the last snapshot, "
        "e.g. type into three fields, choose a status, then click Save. Each step is one of: "
        f"{', '.join(actions)}, aimed and filled like the single tools (in a wait step, locator is what must "
        "match). Every step that could change something is checked on its own, like the single tools. The call "
        "stops at the first step that fails, at a dialog, or when the page goes to another address, and says which "
        "steps ran.",
        {
            "steps": {"type": "array", "items": _step_schema(actions), "description": "The actions, in order"},
            "say": SAY,
        },
        ["steps", "say"],
        said("Working through the steps"),
        _stepper(actions),
    )
