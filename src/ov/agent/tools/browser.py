from __future__ import annotations

import base64
import time
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from ov.agent.engine.guard import Effect
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
from ov.browser.pilot import BUTTONS, MODIFIERS, NO_DIALOG, DialogOpen, Pilot, Point, Target, View
from ov.onevizion.login import PENDING_PATHS

POINTER_LEAD_SECONDS = 0.5
SCROLL_PIXELS = 600
MAX_SCROLL_PIXELS = 5_000
SNAPSHOT_TEXT_CHARS = 6_000
ACTION_TEXT_CHARS = 1_500
GUARD_TEXT_CHARS = 200
DEFAULT_WAIT_SECONDS = 10
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
SCROLLS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
ANSWERS = ("accept", "dismiss")
TAB_ACTIONS = ("switch", "close")
CHANGING_DIALOGS = frozenset({"confirm", "prompt", "beforeunload"})

BLOCKED = (
    "Blocked: {reason}. This would change something and the thread is Read-only. Do not try another way to do it; "
    "report that it needs changes allowed (Ask first or Auto, not Read-only)."
)
REJECTED = "The user rejected this: {say}. Do not retry it."
NOT_SIGNED_IN = "{host} still shows its sign-in page after signing in. Ask the user to check the account."
OFF_INSTANCE = "Stayed on this page: the browser only opens this instance, so it did not go to {urls}."
FRAMES_NOTE = (
    "Frames: parts of this page load inside them. To work on one as a full page, open its path with browser_open."
)
TABS_NOTE = "Tabs: the page opened more windows. You see the shown one; switch or close them with browser_tab."
DIALOG_OPEN = (
    'The page is showing a {kind}: "{message}". It waits until the {kind} is answered: answer it with browser_dialog.'
)
SCREENSHOT_NOTE = "Screenshot attached: {width}x{height}; its pixels are the x and y the browser tools take."
FINAL_SCREENSHOT = "Now: {title} | {url}\nThe final screenshot is attached."

SAY = string_param(
    "One short present-tense sentence the user sees over the browser while this runs, "
    "e.g. 'Opening the Save menu of the work order'"
)
AIM = {
    "ref": int_param("Element number from the last snapshot, shown as [n]"),
    "x": {"type": "number", "description": "Screen x in screenshot pixels; give with y"},
    "y": {"type": "number", "description": "Screen y in screenshot pixels; give with x"},
    "locator": string_param("Playwright selector, e.g. role=button[name='Save'] or text=Continue"),
}
AIM_HELP = "Aim with one of: ref from the last snapshot, x and y from the screenshot, or a Playwright locator."
BUTTON = {"type": "string", "enum": list(BUTTONS), "description": f"Mouse button, default {DEFAULT_BUTTON}"}


def _signed_out(url: str) -> bool:
    return urlsplit(url).path.lower().startswith(PENDING_PATHS)


def _aimed(args: dict[str, Any], prefix: str = "") -> bool:
    return any(args.get(f"{prefix}{key}") is not None for key in AIM)


def _target(args: dict[str, Any], prefix: str = "") -> Target:
    x, y = args.get(f"{prefix}x"), args.get(f"{prefix}y")
    ref = args.get(f"{prefix}ref")
    point = Point(round(float(x)), round(float(y))) if x is not None and y is not None else None
    return Target(ref=int(ref) if ref is not None else None, point=point, locator=args.get(f"{prefix}locator"))


def _elements(view: View) -> str:
    return "\n".join(f"[{e.ref}] {e.describe()} @ {e.point.x},{e.point.y}" for e in view.elements) or "none"


def _frames(view: View) -> str:
    if not view.frames:
        return ""
    lines = [
        f"- {urlsplit(f.url).path}?{urlsplit(f.url).query} @ {f.x},{f.y} {f.width}x{f.height}" for f in view.frames
    ]
    return f"\n\n{FRAMES_NOTE}\n" + "\n".join(lines)


def _tabs(view: View) -> str:
    if len(view.tabs) < 2:
        return ""
    lines = [f"[{t.index}] {t.title or '(untitled)'} | {t.url}{' (shown)' if t.active else ''}" for t in view.tabs]
    return f"\n\n{TABS_NOTE}\n" + "\n".join(lines)


def render(view: View, text_chars: int) -> str:
    text = view.text[:text_chars] or "(empty)"
    more = f"\n[{len(view.text) - text_chars} more chars in the next snapshot]" if len(view.text) > text_chars else ""
    return (
        f"{view.title}\n{view.url}\nScreen {view.width}x{view.height}{_tabs(view)}{_frames(view)}\n\n"
        f"Visible elements (ref, what, click point x,y):\n{_elements(view)}\n\nPage text:\n{text}{more}"
    )


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


def _place(pilot: Pilot) -> str:
    title, url = pilot.where()
    return f"{title} | {urlsplit(url).path}"


def _check(ctx: ToolContext, place: str, action: str, say: str) -> None:
    if ctx.full_access():
        return

    verdict = ctx.judge_page_action(f"<action>{action}</action>\n<page>{place}</page>\n<intent>{say}</intent>")
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


def _result(ctx: ToolContext, pilot: Pilot, done: str) -> str:
    view = pilot.snapshot()
    lines = [done, f"Now: {view.title} | {view.url}"]
    blocked = pilot.take_blocked()
    if blocked:
        lines.append(OFF_INSTANCE.format(urls=", ".join(blocked)))
    if len(view.tabs) > 1:
        lines.append(_tabs(view).strip())

    if _attach(ctx, pilot):
        return "\n".join([*lines, SCREENSHOT_NOTE.format(width=view.width, height=view.height)])
    return "\n".join([*lines, "", render(view, ACTION_TEXT_CHARS)])


def _full(ctx: ToolContext, pilot: Pilot) -> str:
    view = pilot.snapshot()
    page = render(view, SNAPSHOT_TEXT_CHARS)
    if not _attach(ctx, pilot):
        return page
    return f"{page}\n\n{SCREENSHOT_NOTE.format(width=view.width, height=view.height)}"


def _open(args: dict[str, Any], ctx: ToolContext) -> str:
    found = _instance(args, ctx)
    if not found["valid"]:
        _sign_in(ctx, found)

    pilot = ctx.browser.start(found["alias"], found["url"], web_cookies(found["alias"]))
    target = pilot.url_of(str(args.get("path") or ""))
    if urlsplit(target).query:
        _check(ctx, _place(pilot), f"go to {target}", str(args["say"]))

    ctx.browser.navigate(target)
    if not _signed_out(pilot.where()[1]):
        return _full(ctx, pilot)

    _sign_in(ctx, found)
    pilot.add_cookies(web_cookies(found["alias"]))
    ctx.browser.navigate(target)
    if _signed_out(pilot.where()[1]):
        raise ToolError(NOT_SIGNED_IN.format(host=found["host"]))
    return _full(ctx, pilot)


def _snapshot(_: dict[str, Any], ctx: ToolContext) -> str:
    return _full(ctx, ctx.browser.pilot())


def _click(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim = pilot.aim(_target(args))
    button = str(args.get("button") or DEFAULT_BUTTON)
    count = DOUBLE_CLICK if args.get("double") is True else SINGLE_CLICK
    modifiers = [m for m in args.get("modifiers") or [] if m in MODIFIERS]
    verb = "".join(f"{m}+" for m in modifiers) + ("double-" if count == DOUBLE_CLICK else "") + f"{button}-click"
    _check(ctx, _place(pilot), f"{verb} {aim.label}", str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.click(aim.point, button, count, modifiers)
    return _result(ctx, pilot, f"Did {verb} on {aim.label}.")


def _hover(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim = pilot.aim(_target(args))
    _show(ctx, aim.point, press=False)
    pilot.move(aim.point)
    return _result(ctx, pilot, f"Moved the mouse to {aim.label}.")


def _mouse(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim = pilot.aim(_target(args))
    button = str(args.get("button") or DEFAULT_BUTTON)
    down = args["action"] == "down"
    if not down:
        _check(ctx, _place(pilot), f"release the {button} mouse button on {aim.label}", str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.press_mouse(aim.point, button, down)
    return _result(ctx, pilot, f"{'Pressed' if down else 'Released'} the {button} button on {aim.label}.")


def _drag(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    start = pilot.aim(_target(args, "from_"))
    end = pilot.aim(_target(args, "to_"))
    _check(ctx, _place(pilot), f"drag {start.label} and drop it on {end.label}", str(args["say"]))

    _show(ctx, start.point, press=True)
    _show(ctx, end.point, press=True)
    pilot.drag(start.point, end.point)
    return _result(ctx, pilot, f"Dragged {start.label} to {end.label}.")


def _scroll_point(args: dict[str, Any], pilot: Pilot) -> Point:
    if _aimed(args):
        return pilot.aim(_target(args)).point
    view = pilot.snapshot()
    return Point(view.width // 2, view.height // 2)


def _scroll(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    point = _scroll_point(args, pilot)
    pixels = max(1, min(MAX_SCROLL_PIXELS, int(args.get("pixels") or SCROLL_PIXELS)))
    sx, sy = SCROLLS[str(args["direction"])]

    _show(ctx, point, press=False)
    pilot.scroll(point, sx * pixels, sy * pixels)
    return _result(ctx, pilot, f"Scrolled {args['direction']} {pixels}px at ({point.x}, {point.y}).")


def _type(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    text = str(args["text"])
    submit = args.get("submit") is True
    aim = pilot.aim(_target(args)) if _aimed(args) else None
    into = aim.label if aim else "the focused field"
    if submit:
        _check(
            ctx,
            _place(pilot),
            f'type "{text[:GUARD_TEXT_CHARS]}" into {into}, then press {SUBMIT_KEY}',
            str(args["say"]),
        )

    if aim is not None:
        _show(ctx, aim.point, press=True)
        pilot.click(aim.point, DEFAULT_BUTTON, SINGLE_CLICK, [])

    pilot.type(text, args.get("clear") is True)
    if submit:
        pilot.press(SUBMIT_KEY)
    return _result(ctx, pilot, f"Typed into {into}{f' and pressed {SUBMIT_KEY}' if submit else ''}.")


def _press(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    key = str(args["key"]).strip()
    if key not in SAFE_KEYS:
        _check(ctx, _place(pilot), f"press {key} on the focused element", str(args["say"]))
    pilot.press(key)
    return _result(ctx, pilot, f"Pressed {key}.")


def _select(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    aim = pilot.aim(_target(args))
    option = str(args["option"])
    _check(ctx, _place(pilot), f'choose "{option}" in {aim.label}', str(args["say"]))

    _show(ctx, aim.point, press=True)
    pilot.select(int(args["ref"]), option)
    return _result(ctx, pilot, f'Chose "{option}" in {aim.label}.')


def _wait(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    text, locator, url = (str(args.get(k) or "") for k in ("text", "locator", "url_contains"))
    seconds = float(args.get("seconds") or DEFAULT_WAIT_SECONDS)
    if not (text or locator or url):
        pilot.pause(seconds)
        return _result(ctx, pilot, f"Waited {seconds:g}s.")

    pilot.wait_for(text, locator, url, seconds)
    return _result(ctx, pilot, "The page shows it.")


def _dialog(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    dialog = pilot.dialog
    if dialog is None:
        raise ToolError(NO_DIALOG)

    accept = args["action"] == "accept"
    if accept and dialog.kind in CHANGING_DIALOGS:
        action = f'press OK on the {dialog.kind} "{dialog.message[:GUARD_TEXT_CHARS]}"'
        _check(ctx, f"a {dialog.kind} dialog over the page", action, str(args["say"]))

    ctx.browser.answer_dialog(accept, str(args.get("text") or dialog.default))
    return _result(ctx, pilot, f"{'Accepted' if accept else 'Dismissed'} the {dialog.kind}.")


def _tab(args: dict[str, Any], ctx: ToolContext) -> str:
    pilot = ctx.browser.pilot()
    index = int(args["index"])
    if args["action"] == "close":
        ctx.browser.close_tab(index)
        return _result(ctx, pilot, f"Closed tab {index}.")

    ctx.browser.switch_tab(index)
    return _result(ctx, pilot, f"Switched to tab {index}.")


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


def _dialog_aware(handler: Handler) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return handler(args, ctx)
        except DialogOpen as exc:
            return DIALOG_OPEN.format(kind=exc.dialog.kind, message=exc.dialog.message)

    return wrapped


OPEN = Tool(
    "browser_open",
    "Open a signed-in OneVizion instance in the live browser the user watches beside the chat, or go to another "
    "page of it. Only pages of that instance open. Returns the page: title, URL, numbered elements with their "
    "screen position, text and a screenshot.",
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
    "browser_open. Split long tests into a few goals and read each report before the next.",
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
        "Look at the browser: title, URL, screen size, numbered visible elements with a click point x,y, page "
        "text and a screenshot. Element numbers change with every snapshot.",
        {},
        [],
        lambda _: "Looking at the page",
        _snapshot,
    ),
    Tool(
        "browser_click",
        f"Move the mouse to a spot and click it. {AIM_HELP} double=true double-clicks (edits a grid cell, opens a "
        "row), button=right opens a context menu. Anything that could save, run or delete is checked first.",
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
        _click,
    ),
    Tool(
        "browser_hover",
        f"Move the mouse over a spot without clicking, to open hover menus or tooltips. {AIM_HELP}",
        {**AIM, "say": SAY},
        ["say"],
        _said("Moving the mouse"),
        _hover,
    ),
    Tool(
        "browser_mouse",
        f"Press (down) or release (up) a mouse button at a spot, for controls that need a held press. {AIM_HELP} "
        "A release is checked like a click.",
        {**AIM, "action": {"type": "string", "enum": ["down", "up"]}, "button": BUTTON, "say": SAY},
        ["action", "say"],
        _said("Pressing the mouse"),
        _mouse,
    ),
    Tool(
        "browser_drag",
        "Drag from one spot and drop on another. Aim each end with from_ref, from_x and from_y, or from_locator, "
        "and to_ref, to_x and to_y, or to_locator. The drop is checked like a click.",
        {**{f"from_{k}": v for k, v in AIM.items()}, **{f"to_{k}": v for k, v in AIM.items()}, "say": SAY},
        ["say"],
        _said("Dragging"),
        _drag,
    ),
    Tool(
        "browser_scroll",
        "Scroll with the mouse wheel over a spot, so the panel, grid or list under it scrolls. Aim like a click; "
        "without aim it scrolls the middle of the screen.",
        {
            **AIM,
            "direction": {"type": "string", "enum": list(SCROLLS)},
            "pixels": int_param(f"How far, default {SCROLL_PIXELS}"),
            "say": SAY,
        },
        ["direction", "say"],
        _said("Scrolling"),
        _scroll,
    ),
    Tool(
        "browser_type",
        "Type text key by key. Aim at a field to click it first, or omit aim to type into the focused field. "
        f"clear=true deletes what is there first. submit=true presses {SUBMIT_KEY} afterwards, which is checked "
        "like a click.",
        {
            **AIM,
            "text": string_param("Text to type"),
            "clear": {"type": "boolean", "description": "Clear the field first"},
            "submit": {"type": "boolean", "description": f"Press {SUBMIT_KEY} afterwards"},
            "say": SAY,
        },
        ["text", "say"],
        _said("Typing"),
        _type,
    ),
    Tool(
        "browser_press",
        "Press a key or combination, e.g. Enter, Escape, Tab, ArrowDown, ControlOrMeta+A. Keys other than moving "
        "around and deleting text are checked like a click.",
        {"key": string_param("Key as Playwright writes it"), "say": SAY},
        ["key", "say"],
        _said("Pressing a key"),
        _press,
    ),
    Tool(
        "browser_select",
        "Choose an option of a standard dropdown (combobox) by its visible text. Clicking a dropdown also opens "
        "its list on screen as options to click. Checked like a click.",
        {"ref": AIM["ref"], "option": string_param("Visible text of the option"), "say": SAY},
        ["ref", "option", "say"],
        _said("Choosing an option"),
        _select,
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
        _wait,
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
        _dialog,
    ),
    Tool(
        "browser_tab",
        "Show another tab of the browser, or close one. Pages that open a new window get their own tab; the "
        "snapshot lists the tabs by number.",
        {"action": {"type": "string", "enum": list(TAB_ACTIONS)}, "index": int_param("Tab number"), "say": SAY},
        ["action", "index", "say"],
        _said("Switching tabs"),
        _tab,
    ),
]
HANDS = [replace(t, handler=_dialog_aware(t.handler)) for t in HANDS]

MAIN = [OPEN, RUN, CLOSE]
