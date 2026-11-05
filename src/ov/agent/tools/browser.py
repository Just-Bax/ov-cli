from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ov.agent import workspace as project
from ov.agent.engine.browsing import loop_span
from ov.agent.engine.files import within
from ov.agent.engine.guard import Effect
from ov.agent.instances.http import web_session_alive
from ov.agent.instances.ovproc import find_instance, web_cookies
from ov.agent.tools.base import (
    Handler,
    Tool,
    ToolContext,
    ToolError,
    approved,
    int_param,
    serial,
    string_param,
)
from ov.browser.pilot import (
    BUTTONS,
    MODIFIERS,
    NO_DIALOG,
    BrowserError,
    DialogOpen,
    Pilot,
    Point,
    Tab,
    Target,
    View,
)
from ov.onevizion.login import PENDING_PATHS

POINTER_LEAD_SECONDS = 0.15
SCROLL_PIXELS = 600
MAX_SCROLL_PIXELS = 5_000
GUARD_TEXT_CHARS = 200
DEFAULT_WAIT_SECONDS = 10
MAX_STEPS = 12
MAX_UPLOAD_FILES = 10
ATTACHMENTS_DIR = "attachments"
SNAPSHOT_TOOL = "browser_snapshot"
DEFAULT_BUTTON = "left"
SINGLE_CLICK = 1
DOUBLE_CLICK = 2
SUBMIT_KEY = "Enter"
SAFE_KEYS = frozenset(
    {
        "Tab",
        "Shift+Tab",
        "Escape",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "PageUp",
        "PageDown",
        "Home",
        "End",
        "Backspace",
        "Delete",
        "ControlOrMeta+A",
    }
)
VIEW_ROLES = frozenset(
    {
        "textbox",
        "searchbox",
        "combobox",
        "tab",
        "treeitem",
        "row",
        "gridcell",
        "cell",
        "columnheader",
        "rowheader",
        "heading",
        "option",
        "text",
    }
)
REPEATABLE = frozenset({"browser_snapshot", "browser_wait", "browser_press", "browser_scroll"})
SCROLLS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
ANSWERS = ("accept", "dismiss")
TAB_ACTIONS = ("switch", "close")
CHANGING_DIALOGS = frozenset({"confirm", "prompt", "beforeunload"})

BLOCKED = (
    "Blocked: {reason}. This would change something and the thread is Read-only. Do not try another way to do it; "
    "report that it needs changes allowed (Ask first or Auto, not Read-only)."
)
REJECTED = "The user rejected this: {say}. Do not retry it."
GIVE_UP = "take a snapshot, try a different way, or stop and report stuck with what the page shows."
REPEATED = "Stopped: the same {name} ran {count} times in a row without getting anywhere. Do not repeat it; " + GIVE_UP
LOOPED = (
    "Stopped: the last {count} actions went round the same {period} steps with nothing new on the page. Do not go "
    "round again; " + GIVE_UP
)
SAME_PAGE = (
    "Stopped: the last {count} snapshots showed the same page and nothing changed. For something slow use "
    "browser_wait with the text you expect; otherwise stop and report stuck with what the page shows."
)
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
NO_FILES = "Name at least one file to upload."
TOO_MANY_FILES = f"Upload at most {MAX_UPLOAD_FILES} files at once."
OUTSIDE_RUN = "{name} is outside the run folder; only files of this run and its attachments can be uploaded."
NO_RUN_FILE = "No file {name} in the run folder or its attachments."
NOT_SIGNED_IN = "{host} still shows its sign-in page after signing in. Ask the user to check the account."
PREVIEW_QUESTION = "Run the widget {name} in the browser as you on {host}?"
PREVIEW_DETAIL = (
    "The widget's own code runs with your session, the way an External Widget would: it can read and change "
    "whatever your account can on {host}."
)
PREVIEW_BLOCKED = (
    "Not previewed: the widget would run with the user's session, which needs changes allowed in this thread "
    "(Always ask or Auto). Tell the user, or hand them the file to open."
)
PREVIEW_REJECTED = "The user did not allow the preview. Do not retry it."
_PREVIEW_NAME = re.compile(r"[^a-z0-9-]+")
OFF_SITE = "Stayed on this page: the browser only opens this site, so it did not go to {urls}."
TABS_NOTE = "Tabs: the page opened more windows. You see the shown one; switch or close them with browser_tab."
LOADING_NOTE = "The page is still loading; wait or look again if parts are missing."
DIALOG_OPEN = (
    'The page is showing a {kind}: "{message}". It waits until the {kind} is answered: answer it with browser_dialog.'
)
SCREENSHOT_NOTE = "Screenshot attached: {width}x{height}; its pixels are the x and y the browser tools take."
FINAL_SCREENSHOT = "Now: {title} | {url}\nThe final screenshot is attached."

SAY = string_param(
    "One short present-tense sentence the user sees over the browser while this runs, e.g. 'Opening the Save menu'"
)
AIM = {
    "ref": string_param("Element ref from the last snapshot, e.g. e14 or f1e3"),
    "x": {"type": "number", "description": "Screen x in screenshot pixels; give with y"},
    "y": {"type": "number", "description": "Screen y in screenshot pixels; give with x"},
    "locator": string_param("Playwright selector, e.g. role=button[name='Save'] or text=Continue"),
}
AIM_HELP = "Aim with one of: ref from the last snapshot (best), a Playwright locator, or x and y from a screenshot."
BUTTON = {"type": "string", "enum": list(BUTTONS), "description": f"Mouse button, default {DEFAULT_BUTTON}"}


def _signed_out(url: str, host: str) -> bool:
    parts = urlsplit(url)
    return parts.netloc.lower() != host.lower() or parts.path.lower().startswith(PENDING_PATHS)


def _aimed(args: dict[str, Any], prefix: str = "") -> bool:
    return any(args.get(f"{prefix}{key}") not in (None, "") for key in AIM)


def _target(args: dict[str, Any], prefix: str = "") -> Target:
    x, y = args.get(f"{prefix}x"), args.get(f"{prefix}y")
    ref = str(args.get(f"{prefix}ref") or "").strip() or None
    point = Point(round(float(x)), round(float(y))) if x is not None and y is not None else None
    return Target(ref=ref, point=point, locator=args.get(f"{prefix}locator") or None)


def _tabs(tabs: list[Tab]) -> str:
    if len(tabs) < 2:
        return ""
    lines = [f"[{t.index}] {t.title or '(untitled)'} | {t.url}{' (shown)' if t.active else ''}" for t in tabs]
    return f"\n\n{TABS_NOTE}\n" + "\n".join(lines)


def render(view: View) -> str:
    loading = f"\n{LOADING_NOTE}" if view.loading else ""
    return f"{view.title}\n{view.url}\nScreen {view.width}x{view.height}{loading}{_tabs(view.tabs)}\n\n{view.tree}"


def _instance(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    ref = str(args.get("instance") or ctx.instance).strip()
    if not ref:
        raise ToolError("Name the instance to open.")

    found = find_instance(ref)
    if found is None:
        raise ToolError(f"{ref} is not a signed-in instance.")
    return found


def _sign_in(ctx: ToolContext, found: dict[str, Any]) -> None:
    if not ctx.require_login(found["host"], found["tenant"] or ""):
        raise ToolError(f"{found['host']} is not signed in.")


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


def _check(ctx: ToolContext, pilot: Pilot, action: str, say: str) -> None:
    if ctx.full_access():
        return

    title, url = pilot.where()
    place = f"{title} | {urlsplit(url).path}"
    verdict = ctx.judge_page_action(f"<action>{action}</action>\n<page>{place}</page>")
    if verdict.effect != Effect.WRITE:
        return

    if not ctx.can_write():
        raise ToolError(BLOCKED.format(reason=verdict.reason))

    detail = f"{action}\non {place}\n\nCounts as a change: {verdict.reason}"
    if not approved(ctx, say, detail):
        raise ToolError(REJECTED.format(say=say))


def _show(ctx: ToolContext, point: Point, press: bool) -> None:
    ctx.browser.pointer(point, press)
    time.sleep(POINTER_LEAD_SECONDS)


def _attach(ctx: ToolContext, pilot: Pilot) -> bool:
    if not ctx.vision:
        return False
    data = base64.b64encode(pilot.screenshot()).decode()
    ctx.attach_image(f"browser-{serial()}.jpg", f"data:image/jpeg;base64,{data}")
    return True


def _result(pilot: Pilot, done: str) -> str:
    title, url = pilot.where()
    lines = [done, f"Now: {title} | {url}"]
    blocked = pilot.take_blocked()
    if blocked:
        lines.append(OFF_SITE.format(urls=", ".join(blocked)))
    return "\n".join(lines) + _tabs(pilot.tabs())


def _look(ctx: ToolContext, pilot: Pilot, screenshot: bool) -> str:
    view = pilot.snapshot()
    ctx.browser.saw(f"{view.url}\n{view.tree}")
    page = render(view)
    if not screenshot or not _attach(ctx, pilot):
        return page
    return f"{page}\n\n{SCREENSHOT_NOTE.format(width=view.width, height=view.height)}"


def _open(args: dict[str, Any], ctx: ToolContext) -> str:
    found = _instance(args, ctx)
    if not found["valid"] or not web_session_alive(found["alias"]):
        _sign_in(ctx, found)

    pilot = ctx.browser.start(found["alias"], found["url"], web_cookies(found["alias"]))
    target = pilot.url_of(str(args.get("path") or ""))
    if urlsplit(target).query:
        _check(ctx, pilot, f"go to {target}", str(args["say"]))

    ctx.browser.navigate(target)
    if not _signed_out(pilot.where()[1], found["host"]):
        return _look(ctx, pilot, screenshot=True)

    _sign_in(ctx, found)
    pilot.add_cookies(web_cookies(found["alias"]))
    ctx.browser.navigate(target)
    if _signed_out(pilot.where()[1], found["host"]):
        raise ToolError(NOT_SIGNED_IN.format(host=found["host"]))
    return _look(ctx, pilot, screenshot=True)


def _snapshot(args: dict[str, Any], ctx: ToolContext) -> str:
    page = _look(ctx, ctx.browser.pilot(), screenshot=args.get("screenshot") is True)
    period = ctx.browser.looping(SNAPSHOT_TOOL)
    if period:
        raise _loop_error(SNAPSHOT_TOOL, period)
    return page


def _click(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    target = _target(args)
    aim = pilot.aim(target)
    button = str(args.get("button") or DEFAULT_BUTTON)
    count = DOUBLE_CLICK if args.get("double") is True else SINGLE_CLICK
    modifiers = [m for m in args.get("modifiers") or [] if m in MODIFIERS]
    verb = "".join(f"{m}+" for m in modifiers) + ("double-" if count == DOUBLE_CLICK else "") + f"{button}-click"
    if aim.role not in VIEW_ROLES:
        _check(ctx, pilot, f"{verb} {aim.label}", str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.click(target, aim.point, button, count, modifiers)
    return f"Did {verb} on {aim.label}."


def _hover(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    target = _target(args)
    aim = pilot.aim(target)
    _show(ctx, aim.point, press=False)
    pilot.move(target, aim.point)
    return f"Moved the mouse to {aim.label}."


def _mouse(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim = pilot.aim(_target(args))
    button = str(args.get("button") or DEFAULT_BUTTON)
    down = args["action"] == "down"
    if not down:
        _check(ctx, pilot, f"release the {button} mouse button on {aim.label}", str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.press_mouse(aim.point, button, down)
    return f"{'Pressed' if down else 'Released'} the {button} button on {aim.label}."


def _drag(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    start = pilot.aim(_target(args, "from_"))
    end = pilot.aim(_target(args, "to_"))
    _check(ctx, pilot, f"drag {start.label} and drop it on {end.label}", str(args["say"]))

    _show(ctx, start.point, press=True)
    _show(ctx, end.point, press=True)
    pilot.drag(start.point, end.point)
    return f"Dragged {start.label} to {end.label}."


def _scroll(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    point = pilot.aim(_target(args)).point if _aimed(args) else pilot.center()
    pixels = max(1, min(MAX_SCROLL_PIXELS, int(args.get("pixels") or SCROLL_PIXELS)))
    sx, sy = SCROLLS[str(args["direction"])]

    _show(ctx, point, press=False)
    pilot.scroll(point, sx * pixels, sy * pixels)
    return f"Scrolled {args['direction']} {pixels}px at ({point.x}, {point.y})."


def _type(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    text = str(args["text"])
    submit = args.get("submit") is True
    target = _target(args) if _aimed(args) else None
    aim = pilot.aim(target) if target else None
    into = aim.label if aim else "the focused field"
    if submit:
        _check(ctx, pilot, f'type "{text[:GUARD_TEXT_CHARS]}" into {into}, then press {SUBMIT_KEY}', str(args["say"]))

    if aim is not None:
        _show(ctx, aim.point, press=True)
    pilot.type(target, aim.point if aim else None, text, args.get("clear") is True)
    if submit:
        pilot.press(SUBMIT_KEY)
    return f"Typed into {into}{f' and pressed {SUBMIT_KEY}' if submit else ''}."


def _press(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    key = str(args["key"]).strip()
    if key not in SAFE_KEYS:
        _check(ctx, pilot, f"press {key} on the focused element", str(args["say"]))
    pilot.press(key)
    return f"Pressed {key}."


def _select(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    target = _target(args)
    aim = pilot.aim(target)
    option = str(args["option"])
    _check(ctx, pilot, f'choose "{option}" in {aim.label}', str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.select(target, option)
    return f'Chose "{option}" in {aim.label}.'


def _wait(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    text, locator, url = (str(args.get(k) or "") for k in ("text", "locator", "url_contains"))
    seconds = float(args.get("seconds") or DEFAULT_WAIT_SECONDS)
    if not (text or locator or url):
        pilot.pause(seconds)
        return f"Waited {seconds:g}s."

    pilot.wait_for(text, locator, url, seconds)
    return "The page shows it."


def _dialog(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    dialog = pilot.dialog
    if dialog is None:
        raise ToolError(NO_DIALOG)

    accept = args["action"] == "accept"
    if accept and dialog.kind in CHANGING_DIALOGS:
        action = f'press OK on the {dialog.kind} "{dialog.message[:GUARD_TEXT_CHARS]}"'
        _check(ctx, pilot, action, str(args["say"]))

    ctx.browser.answer_dialog(accept, str(args.get("text") or dialog.default))
    return f"{'Accepted' if accept else 'Dismissed'} the {dialog.kind}."


def _tab(args: dict[str, Any], ctx: ToolContext) -> str:
    index = int(args["index"])
    if args["action"] == "close":
        ctx.browser.close_tab(index)
        return f"Closed tab {index}."
    ctx.browser.switch_tab(index)
    return f"Switched to tab {index}."


def _upload(args: dict[str, Any], ctx: ToolContext) -> str:
    names = [str(name) for name in args.get("files") or []]
    if not names:
        raise ToolError(NO_FILES)
    if len(names) > MAX_UPLOAD_FILES:
        raise ToolError(TOO_MANY_FILES)

    files = [_run_file(name, ctx) for name in names]
    listed = ", ".join(f.name for f in files)
    pilot = ctx.browser.pilot()
    target = _target(args)
    aim = pilot.aim(target)
    _check(ctx, pilot, f"upload {listed} with {aim.label}", str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.upload(target, aim.point, [str(f) for f in files])
    return f"Uploaded {listed} with {aim.label}."


def _planned(args: dict[str, Any]) -> list[dict[str, Any]]:
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ToolError(NO_STEPS)
    if len(steps) > MAX_STEPS:
        raise ToolError(TOO_MANY_STEPS)

    planned = []
    for number, step in enumerate(steps, start=1):
        action = step.get("action") if isinstance(step, dict) else None
        if action not in STEP_ACTIONS:
            raise ToolError(UNKNOWN_STEP.format(number=number, action=action, actions=", ".join(STEP_ACTIONS)))
        if action in AIMED_STEPS and not _aimed(step):
            raise ToolError(STEP_NEEDS_AIM.format(number=number, action=action))

        missing = [name for name in STEP_FIELDS.get(action, ()) if step.get(name) in (None, "", [])]
        if missing:
            raise ToolError(STEP_NEEDS.format(number=number, action=action, fields=", ".join(missing)))
        planned.append({**step, "say": str(step.get("say") or args["say"])})

    return planned


def _do_steps(steps: list[dict[str, Any]], ctx: ToolContext, pilot: Pilot, done: list[str]) -> None:
    start = pilot.where()[1]
    for number, step in enumerate(steps, start=1):
        ctx.cancel.check()
        try:
            done.append(f"{number}. {STEP_ACTIONS[step['action']](step, ctx)}")
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


def _steps(args: dict[str, Any], ctx: ToolContext) -> str:
    steps = _planned(args)
    pilot = ctx.browser.pilot()
    done: list[str] = []
    try:
        _do_steps(steps, ctx, pilot, done)
        return _result(pilot, "\n".join(done))
    except DialogOpen as exc:
        return "\n".join([*done, DIALOG_OPEN.format(kind=exc.dialog.kind, message=exc.dialog.message)])


def _run(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    report = ctx.drive_browser(str(args["goal"]), ctx.cancel)
    if not ctx.browser.live or not _attach(ctx, pilot):
        return report
    title, url = pilot.where()
    return f"{report}\n\n{FINAL_SCREENSHOT.format(title=title, url=url)}"


def _close(_: dict[str, Any], ctx: ToolContext) -> str:
    ctx.browser.close()
    return "Closed the browser."


def _said(fallback: str) -> Any:
    return lambda args: str(args.get("say") or fallback)


def _reported(action: Handler) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        done = action(args, ctx)
        return _result(ctx.browser.pilot(), done)

    return wrapped


def _unsaid(args: dict[str, Any]) -> dict[str, Any]:
    plain = {k: v for k, v in args.items() if k != "say"}
    if isinstance(plain.get("steps"), list):
        plain["steps"] = [_unsaid(step) if isinstance(step, dict) else step for step in plain["steps"]]
    return plain


def _loop_error(name: str, period: int) -> ToolError:
    count = loop_span(period)
    if period > 1:
        return ToolError(LOOPED.format(count=count, period=period))
    if name == SNAPSHOT_TOOL:
        return ToolError(SAME_PAGE.format(count=count))
    return ToolError(REPEATED.format(name=name, count=count))


def _dialog_aware(handler: Handler) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return handler(args, ctx)
        except DialogOpen as exc:
            return DIALOG_OPEN.format(kind=exc.dialog.kind, message=exc.dialog.message)

    return wrapped


def _not_repeated(name: str, handler: Handler) -> Handler:
    if name in REPEATABLE:
        return handler

    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        period = ctx.browser.looping(json.dumps({"tool": name, **_unsaid(args)}, sort_keys=True))
        if period:
            raise _loop_error(name, period)
        return handler(args, ctx)

    return wrapped


OPEN = Tool(
    "browser_open",
    "Open a signed-in OneVizion instance in the live browser the user watches beside the chat, or go to another "
    "page of it. Only pages of that instance open. Returns the page as an accessibility snapshot with element refs, "
    "and a screenshot.",
    {
        "instance": string_param("Instance alias or host. Defaults to the run's instance."),
        "path": string_param("Path on the instance, e.g. '/form/ConfigAppForm.do?id=1'. Omit for home."),
        "say": SAY,
    },
    ["say"],
    _said("Opening the browser"),
    _open,
)

RUN = Tool(
    "browser_run",
    "Hand one browser task to a fast assistant that drives the mouse and keyboard while the user watches, and "
    "reports back. Give a concrete goal: where to start, the steps or the outcome to reach, what to check, and "
    "when to stop, e.g. 'On the open Kafka Staging form, set Status to Staged, click Save, then check the Status "
    "field shows Staged'. Every change is still checked and may wait for the user's approval. Returns a report "
    "starting with Result: done, stuck or failed, and the final screenshot. Open the browser first with "
    "browser_open. Split long tests into a few goals and read each report before the next. To upload a file, "
    "name it in the goal; only files in the run folder or its attachments can be uploaded.",
    {"goal": string_param("The task, its steps and the expected result"), "say": SAY},
    ["goal", "say"],
    _said("Working in the browser"),
    _run,
)

CLOSE = Tool(
    "browser_close",
    "Close the browser when the user is done with it.",
    {},
    [],
    lambda _: "Closing the browser",
    _close,
)

HANDS = [
    OPEN,
    Tool(
        "browser_snapshot",
        "Look at the page: title, URL, tabs and its accessibility tree, where every element you can act on has a "
        "ref like [ref=e14] or [ref=f1e3]; pass it exactly. Refs stay valid until the page changes; after a "
        "navigation or a new dialog take a new snapshot. Actions do not return the page, so snapshot when you need "
        "to see what changed. screenshot=true also attaches an image; ask for it only when the layout matters or "
        "the tree is not enough, and aim by x and y only from that image.",
        {"screenshot": {"type": "boolean", "description": "Also attach a screenshot"}},
        [],
        lambda _: "Looking at the page",
        _snapshot,
    ),
    Tool(
        "browser_click",
        f"Click an element. {AIM_HELP} double=true double-clicks (edits a grid cell, opens a row), button=right "
        "opens a context menu. Fails fast with the reason when something covers the element. Anything that could "
        "save, run or delete is checked first. Returns only what was clicked and the page URL.",
        {
            **AIM,
            "button": BUTTON,
            "double": {"type": "boolean", "description": "Double-click"},
            "modifiers": {
                "type": "array",
                "items": {"type": "string", "enum": list(MODIFIERS)},
                "description": "Keys held during the click",
            },
            "say": SAY,
        },
        ["say"],
        _said("Clicking"),
        _reported(_click),
    ),
    Tool(
        "browser_hover",
        f"Move the mouse over an element without clicking, to open hover menus or tooltips. {AIM_HELP}",
        {**AIM, "say": SAY},
        ["say"],
        _said("Moving the mouse"),
        _reported(_hover),
    ),
    Tool(
        "browser_mouse",
        f"Press (down) or release (up) a mouse button at a spot, for controls that need a held press. {AIM_HELP} "
        "A release is checked like a click.",
        {**AIM, "action": {"type": "string", "enum": ["down", "up"]}, "button": BUTTON, "say": SAY},
        ["action", "say"],
        _said("Pressing the mouse"),
        _reported(_mouse),
    ),
    Tool(
        "browser_drag",
        "Drag from one spot and drop on another. Aim each end with from_ref, from_locator, or from_x and from_y, "
        "and to_ref, to_locator, or to_x and to_y. The drop is checked like a click.",
        {**{f"from_{k}": v for k, v in AIM.items()}, **{f"to_{k}": v for k, v in AIM.items()}, "say": SAY},
        ["say"],
        _said("Dragging"),
        _reported(_drag),
    ),
    Tool(
        "browser_scroll",
        "Scroll with the mouse wheel over an element, so the panel, grid or list under it scrolls. Aim like a "
        "click; without aim it scrolls the middle of the screen.",
        {
            **AIM,
            "direction": {"type": "string", "enum": list(SCROLLS)},
            "pixels": int_param(f"How far, default {SCROLL_PIXELS}"),
            "say": SAY,
        },
        ["direction", "say"],
        _said("Scrolling"),
        _reported(_scroll),
    ),
    Tool(
        "browser_type",
        "Type text. Aim at a field to click it first, or omit aim to type into the focused field. clear=true "
        f"deletes what is there first. submit=true presses {SUBMIT_KEY} afterwards, which is checked like a click.",
        {
            **AIM,
            "text": string_param("Text to type"),
            "clear": {"type": "boolean", "description": "Clear the field first"},
            "submit": {"type": "boolean", "description": f"Press {SUBMIT_KEY} afterwards"},
            "say": SAY,
        },
        ["text", "say"],
        _said("Typing"),
        _reported(_type),
    ),
    Tool(
        "browser_press",
        "Press a key or combination, e.g. Enter, Escape, Tab, ArrowDown, ControlOrMeta+A. Keys other than moving "
        "around and deleting text are checked like a click.",
        {"key": string_param("Key as Playwright writes it"), "say": SAY},
        ["key", "say"],
        _said("Pressing a key"),
        _reported(_press),
    ),
    Tool(
        "browser_select",
        "Choose an option of a standard dropdown (a combobox with option children in the snapshot) by its visible "
        "text. Custom dropdowns are not standard: click them open and click the option instead. Checked like a "
        "click.",
        {
            "ref": AIM["ref"],
            "locator": AIM["locator"],
            "option": string_param("Visible text of the option"),
            "say": SAY,
        },
        ["option", "say"],
        _said("Choosing an option"),
        _reported(_select),
    ),
    Tool(
        "browser_wait",
        "Wait until the page shows a text, matches a Playwright locator, or its URL contains a part. Use it after "
        "starting something slow instead of looking again and again. With only seconds it just pauses.",
        {
            "text": string_param("Text that must appear"),
            "locator": string_param("Playwright selector that must match"),
            "url_contains": string_param("Part the URL must contain"),
            "seconds": int_param(f"Longest wait, default {DEFAULT_WAIT_SECONDS}"),
            "say": SAY,
        },
        ["say"],
        _said("Waiting for the page"),
        _reported(_wait),
    ),
    Tool(
        "browser_dialog",
        "Answer the alert, confirm, prompt or leave-page dialog the page is showing; the page waits until it is "
        "answered. action=accept presses OK, dismiss presses Cancel. text fills a prompt. Accepting a confirm, "
        "prompt or leave-page dialog is checked like a click.",
        {
            "action": {"type": "string", "enum": list(ANSWERS)},
            "text": string_param("Answer for a prompt"),
            "say": SAY,
        },
        ["action", "say"],
        _said("Answering the dialog"),
        _reported(_dialog),
    ),
    Tool(
        "browser_tab",
        "Show another tab of the browser, or close one. Pages that open a new window get their own tab; the "
        "snapshot lists the tabs by number.",
        {"action": {"type": "string", "enum": list(TAB_ACTIONS)}, "index": int_param("Tab number"), "say": SAY},
        ["action", "index", "say"],
        _said("Switching tabs"),
        _reported(_tab),
    ),
]
STEP_ACTIONS: dict[str, Handler] = {
    "click": _click,
    "type": _type,
    "press": _press,
    "select": _select,
    "hover": _hover,
    "scroll": _scroll,
    "wait": _wait,
    "upload": _upload,
}
AIMED_STEPS = frozenset({"click", "select", "hover", "upload"})
STEP_FIELDS = {
    "type": ("text",),
    "press": ("key",),
    "select": ("option",),
    "scroll": ("direction",),
    "upload": ("files",),
}
FILES = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Files by name in the run folder or its attachments, e.g. report.pdf",
}
STEP = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(STEP_ACTIONS)},
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

HANDS += [
    Tool(
        "browser_steps",
        f"Do up to {MAX_STEPS} actions in a row in one call, when you already know them from the last snapshot, "
        "e.g. type into three fields, choose a status, then click Save. Each step is one of: "
        f"{', '.join(STEP_ACTIONS)}, aimed and filled like the single tools (in a wait step, locator is what must "
        "match). Every step that could change something is checked on its own, like the single tools. The call "
        "stops at the first step that fails, at a dialog, or when the page goes to another address, and says which "
        "steps ran.",
        {"steps": {"type": "array", "items": STEP, "description": "The actions, in order"}, "say": SAY},
        ["steps", "say"],
        _said("Working through the steps"),
        _steps,
    ),
    Tool(
        "browser_upload",
        "Upload files with a file field or an upload button: it clicks the element and picks the files in the file "
        f"picker that opens. {AIM_HELP} Only files of this run (the run folder or its attachments) can be uploaded. "
        "Checked like a click.",
        {**AIM, "files": FILES, "say": SAY},
        ["files", "say"],
        _said("Uploading a file"),
        _reported(_upload),
    ),
]
HANDS = [replace(t, handler=_dialog_aware(_not_repeated(t.name, t.handler))) for t in HANDS]


def _widget_page(name: str, ctx: ToolContext) -> str:
    in_run = within(ctx.work_dir, name)
    if in_run.is_file():
        return in_run.read_text(encoding="utf-8")
    if project.configured():
        return project.text_of(name)
    raise ToolError(f"No file {name} in the run folder, and no workspace is set.")


def _preview(args: dict[str, Any], ctx: ToolContext) -> str:
    file = str(args["file"])
    page = _widget_page(file, ctx)
    found = _instance(args, ctx)
    name = _PREVIEW_NAME.sub("-", Path(file).stem.lower()).strip("-") or "widget"

    if not ctx.can_write():
        raise ToolError(PREVIEW_BLOCKED)
    if not approved(
        ctx, PREVIEW_QUESTION.format(name=name, host=found["host"]), PREVIEW_DETAIL.format(host=found["host"])
    ):
        raise ToolError(PREVIEW_REJECTED)

    _open({"instance": found["alias"], "say": args["say"]}, ctx)
    pilot = ctx.browser.pilot()
    ctx.browser.navigate(pilot.preview(name, page))
    return _look(ctx, pilot, screenshot=True)


PREVIEW = Tool(
    "browser_preview",
    "Run a single-file HTML widget you built inside the instance, in the live browser, the way an External Widget "
    "runs: same origin, the user's session, so its token request and API calls hit live data. Nothing is deployed. "
    "Use it to check a widget before handing the file over; then look at it with browser_run or the snapshot it "
    "returns. Needs changes allowed and the user's approval, because the widget's code acts as the user.",
    {
        "file": string_param("The widget HTML: a file in the run folder or a path in the workspace"),
        "instance": string_param("Instance alias or host. Defaults to the run's instance."),
        "say": SAY,
    },
    ["file", "say"],
    _said("Opening the widget preview"),
    _preview,
)

MAIN = [OPEN, PREVIEW, RUN, CLOSE]
