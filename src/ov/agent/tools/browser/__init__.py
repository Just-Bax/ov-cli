from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from ov.agent.engine.files import within
from ov.agent.tools.base import Handler, ToolContext, ToolError
from ov.agent.tools.browser import controls, specs
from ov.agent.tools.browser.guard import GUARD_TEXT_CHARS, VIEW_ROLES, check
from ov.agent.tools.browser.loops import not_repeated
from ov.agent.tools.browser.page import OFF_SITE, dialog_aware, reported
from ov.agent.tools.browser.page import result as _result
from ov.agent.tools.browser.session import CLOSE, OPEN, PREVIEW, RUN
from ov.agent.tools.browser.session import signed_out as _signed_out
from ov.agent.tools.browser.specs import DEFAULT_BUTTON, SCROLL_PIXELS, SCROLLS, SUBMIT_KEY, aimed, target
from ov.agent.tools.browser.steps import steps_tool
from ov.browser.model import MODIFIERS, Point

__all__ = ["HANDS", "MAIN", "OFF_SITE", "POINTER_LEAD_SECONDS", "_result", "_signed_out"]

POINTER_LEAD_SECONDS = 0.15
MAX_SCROLL_PIXELS = 5_000
MAX_UPLOAD_FILES = 10
ATTACHMENTS_DIR = "attachments"
SINGLE_CLICK = 1
DOUBLE_CLICK = 2

NO_FILES = "Name at least one file to upload."
TOO_MANY_FILES = f"Upload at most {MAX_UPLOAD_FILES} files at once."
OUTSIDE_RUN = "{name} is outside the run folder; only files of this run and its attachments can be uploaded."
NO_RUN_FILE = "No file {name} in the run folder or its attachments."


def _show(ctx: ToolContext, point: Point, press: bool) -> None:
    ctx.browser.pointer(point, press)
    time.sleep(POINTER_LEAD_SECONDS)


def _run_file(name: str, ctx: ToolContext) -> Path:
    try:
        path = within(ctx.work_dir, name)
        if not path.is_file():
            path = within(ctx.work_dir / ATTACHMENTS_DIR, Path(name).name)
    except ValueError:
        raise ToolError(OUTSIDE_RUN.format(name=name)) from None

    if not path.is_file():
        raise ToolError(NO_RUN_FILE.format(name=name))
    return path


def _click(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim_at = target(args)
    aim = pilot.aim(aim_at)
    button = str(args.get("button") or DEFAULT_BUTTON)
    count = DOUBLE_CLICK if args.get("double") is True else SINGLE_CLICK
    modifiers = [m for m in args.get("modifiers") or [] if m in MODIFIERS]
    verb = "".join(f"{m}+" for m in modifiers) + ("double-" if count == DOUBLE_CLICK else "") + f"{button}-click"
    if aim.role not in VIEW_ROLES:
        check(ctx, pilot, f"{verb} {aim.label}", str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.click(aim_at, aim.point, button, count, modifiers)
    return f"Did {verb} on {aim.label}."


def _hover(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim_at = target(args)
    aim = pilot.aim(aim_at)
    _show(ctx, aim.point, press=False)
    pilot.move(aim_at, aim.point)
    return f"Moved the mouse to {aim.label}."


def _mouse(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim = pilot.aim(target(args))
    button = str(args.get("button") or DEFAULT_BUTTON)
    down = args["action"] == "down"
    if not down:
        check(ctx, pilot, f"release the {button} mouse button on {aim.label}", str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.press_mouse(aim.point, button, down)
    return f"{'Pressed' if down else 'Released'} the {button} button on {aim.label}."


def _drag(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    start = pilot.aim(target(args, "from_"))
    end = pilot.aim(target(args, "to_"))
    check(ctx, pilot, f"drag {start.label} and drop it on {end.label}", str(args["say"]))

    _show(ctx, start.point, press=True)
    _show(ctx, end.point, press=True)
    pilot.drag(start.point, end.point)
    return f"Dragged {start.label} to {end.label}."


def _scroll(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    point = pilot.aim(target(args)).point if aimed(args) else pilot.center()
    pixels = max(1, min(MAX_SCROLL_PIXELS, int(args.get("pixels") or SCROLL_PIXELS)))
    sx, sy = SCROLLS[str(args["direction"])]

    _show(ctx, point, press=False)
    pilot.scroll(point, sx * pixels, sy * pixels)
    return f"Scrolled {args['direction']} {pixels}px at ({point.x}, {point.y})."


def _type(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    text = str(args["text"])
    submit = args.get("submit") is True
    aim_at = target(args) if aimed(args) else None
    aim = pilot.aim(aim_at) if aim_at else None
    into = aim.label if aim else "the focused field"
    if submit:
        check(ctx, pilot, f'type "{text[:GUARD_TEXT_CHARS]}" into {into}, then press {SUBMIT_KEY}', str(args["say"]))

    if aim is not None:
        _show(ctx, aim.point, press=True)
    pilot.type(aim_at, aim.point if aim else None, text, args.get("clear") is True)
    if submit:
        pilot.press(SUBMIT_KEY)
    return f"Typed into {into}{f' and pressed {SUBMIT_KEY}' if submit else ''}."


def _select(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim_at = target(args)
    aim = pilot.aim(aim_at)
    option = str(args["option"])
    check(ctx, pilot, f'choose "{option}" in {aim.label}', str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.select(aim_at, option)
    return f'Chose "{option}" in {aim.label}.'


def _upload(args: dict[str, Any], ctx: ToolContext) -> str:
    names = [str(name) for name in args.get("files") or []]
    if not names:
        raise ToolError(NO_FILES)
    if len(names) > MAX_UPLOAD_FILES:
        raise ToolError(TOO_MANY_FILES)

    files = [_run_file(name, ctx) for name in names]
    listed = ", ".join(f.name for f in files)
    pilot = ctx.browser.pilot()
    aim_at = target(args)
    aim = pilot.aim(aim_at)
    check(ctx, pilot, f"upload {listed} with {aim.label}", str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.upload(aim_at, aim.point, [str(f) for f in files])
    return f"Uploaded {listed} with {aim.label}."


STEP_ACTIONS: dict[str, Handler] = {
    "click": _click,
    "type": _type,
    "press": controls.press,
    "select": _select,
    "hover": _hover,
    "scroll": _scroll,
    "wait": controls.wait,
    "upload": _upload,
}

HANDS = [
    OPEN,
    specs.SNAPSHOT(controls.snapshot),
    specs.CLICK(reported(_click)),
    specs.HOVER(reported(_hover)),
    specs.MOUSE(reported(_mouse)),
    specs.DRAG(reported(_drag)),
    specs.SCROLL(reported(_scroll)),
    specs.TYPE(reported(_type)),
    specs.PRESS(reported(controls.press)),
    specs.SELECT(reported(_select)),
    specs.WAIT(reported(controls.wait)),
    specs.DIALOG(reported(controls.dialog)),
    specs.TAB(reported(controls.tab)),
    steps_tool(STEP_ACTIONS),
    specs.UPLOAD(reported(_upload)),
]
HANDS = [replace(t, handler=dialog_aware(not_repeated(t.name, t.handler))) for t in HANDS]

MAIN = [OPEN, PREVIEW, RUN, CLOSE]
