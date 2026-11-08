from __future__ import annotations

from functools import partial
from typing import Any

from ov.agent.tools.base import Tool, int_param, string_param
from ov.browser.model import BUTTONS, MODIFIERS, Point, Target

SCROLL_PIXELS = 600
DEFAULT_WAIT_SECONDS = 10
DEFAULT_BUTTON = "left"
SUBMIT_KEY = "Enter"
SCROLLS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
ANSWERS = ("accept", "dismiss")
TAB_ACTIONS = ("switch", "close")

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
FILES = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Files by name in the run folder or its attachments, e.g. report.pdf",
}


def said(fallback: str) -> Any:
    return lambda args: str(args.get("say") or fallback)


def aimed(args: dict[str, Any], prefix: str = "") -> bool:
    return any(args.get(f"{prefix}{key}") not in (None, "") for key in AIM)


def target(args: dict[str, Any], prefix: str = "") -> Target:
    x, y = args.get(f"{prefix}x"), args.get(f"{prefix}y")
    ref = str(args.get(f"{prefix}ref") or "").strip() or None
    point = Point(round(float(x)), round(float(y))) if x is not None and y is not None else None
    return Target(ref=ref, point=point, locator=args.get(f"{prefix}locator") or None)


SNAPSHOT = partial(
    Tool,
    "browser_snapshot",
    "Look at the page: title, URL, tabs and its accessibility tree, where every element you can act on has a "
    "ref like [ref=e14] or [ref=f1e3]; pass it exactly. Refs stay valid until the page changes; after a "
    "navigation or a new dialog take a new snapshot. Actions do not return the page, so snapshot when you need "
    "to see what changed. screenshot=true also attaches an image; ask for it only when the layout matters or "
    "the tree is not enough, and aim by x and y only from that image.",
    {"screenshot": {"type": "boolean", "description": "Also attach a screenshot"}},
    [],
    lambda _: "Looking at the page",
)
CLICK = partial(
    Tool,
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
    said("Clicking"),
)
HOVER = partial(
    Tool,
    "browser_hover",
    f"Move the mouse over an element without clicking, to open hover menus or tooltips. {AIM_HELP}",
    {**AIM, "say": SAY},
    ["say"],
    said("Moving the mouse"),
)
MOUSE = partial(
    Tool,
    "browser_mouse",
    f"Press (down) or release (up) a mouse button at a spot, for controls that need a held press. {AIM_HELP} "
    "A release is checked like a click.",
    {**AIM, "action": {"type": "string", "enum": ["down", "up"]}, "button": BUTTON, "say": SAY},
    ["action", "say"],
    said("Pressing the mouse"),
)
DRAG = partial(
    Tool,
    "browser_drag",
    "Drag from one spot and drop on another. Aim each end with from_ref, from_locator, or from_x and from_y, "
    "and to_ref, to_locator, or to_x and to_y. The drop is checked like a click.",
    {**{f"from_{k}": v for k, v in AIM.items()}, **{f"to_{k}": v for k, v in AIM.items()}, "say": SAY},
    ["say"],
    said("Dragging"),
)
SCROLL = partial(
    Tool,
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
    said("Scrolling"),
)
TYPE = partial(
    Tool,
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
    said("Typing"),
)
PRESS = partial(
    Tool,
    "browser_press",
    "Press a key or combination, e.g. Enter, Escape, Tab, ArrowDown, ControlOrMeta+A. Keys other than moving "
    "around and deleting text are checked like a click.",
    {"key": string_param("Key as Playwright writes it"), "say": SAY},
    ["key", "say"],
    said("Pressing a key"),
)
SELECT = partial(
    Tool,
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
    said("Choosing an option"),
)
WAIT = partial(
    Tool,
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
    said("Waiting for the page"),
)
DIALOG = partial(
    Tool,
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
    said("Answering the dialog"),
)
TAB = partial(
    Tool,
    "browser_tab",
    "Show another tab of the browser, or close one. Pages that open a new window get their own tab; the "
    "snapshot lists the tabs by number.",
    {"action": {"type": "string", "enum": list(TAB_ACTIONS)}, "index": int_param("Tab number"), "say": SAY},
    ["action", "index", "say"],
    said("Switching tabs"),
)
UPLOAD = partial(
    Tool,
    "browser_upload",
    "Upload files with a file field or an upload button: it clicks the element and picks the files in the file "
    f"picker that opens. {AIM_HELP} Only files of this run (the run folder or its attachments) can be uploaded. "
    "Checked like a click.",
    {**AIM, "files": FILES, "say": SAY},
    ["files", "say"],
    said("Uploading a file"),
)
