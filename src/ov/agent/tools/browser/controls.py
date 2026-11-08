from __future__ import annotations

from typing import Any

from ov.agent.tools.base import ToolContext, ToolError
from ov.agent.tools.browser.guard import CHANGING_DIALOGS, GUARD_TEXT_CHARS, SAFE_KEYS, check
from ov.agent.tools.browser.loops import SNAPSHOT_TOOL, loop_error
from ov.agent.tools.browser.page import look
from ov.agent.tools.browser.specs import DEFAULT_WAIT_SECONDS
from ov.browser.dialogs import NO_DIALOG


def snapshot(args: dict[str, Any], ctx: ToolContext) -> str:
    page = look(ctx, ctx.browser.pilot(), screenshot=args.get("screenshot") is True)
    period = ctx.browser.looping(SNAPSHOT_TOOL)
    if period:
        raise loop_error(SNAPSHOT_TOOL, period)
    return page


def press(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    key = str(args["key"]).strip()
    if key not in SAFE_KEYS:
        check(ctx, pilot, f"press {key} on the focused element", str(args["say"]))
    pilot.press(key)
    return f"Pressed {key}."


def wait(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    text, locator, url = (str(args.get(k) or "") for k in ("text", "locator", "url_contains"))
    seconds = float(args.get("seconds") or DEFAULT_WAIT_SECONDS)
    if not (text or locator or url):
        pilot.pause(seconds)
        return f"Waited {seconds:g}s."

    pilot.wait_for(text, locator, url, seconds)
    return "The page shows it."


def dialog(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    shown = pilot.dialog
    if shown is None:
        raise ToolError(NO_DIALOG)

    accept = args["action"] == "accept"
    if accept and shown.kind in CHANGING_DIALOGS:
        action = f'press OK on the {shown.kind} "{shown.message[:GUARD_TEXT_CHARS]}"'
        check(ctx, pilot, action, str(args["say"]))

    ctx.browser.answer_dialog(accept, str(args.get("text") or shown.default))
    return f"{'Accepted' if accept else 'Dismissed'} the {shown.kind}."


def tab(args: dict[str, Any], ctx: ToolContext) -> str:
    index = int(args["index"])
    if args["action"] == "close":
        ctx.browser.close_tab(index)
        return f"Closed tab {index}."
    ctx.browser.switch_tab(index)
    return f"Switched to tab {index}."
