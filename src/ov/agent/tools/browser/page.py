from __future__ import annotations

import base64
from typing import Any

from ov.agent.tools.base import Handler, ToolContext, serial
from ov.browser.model import DialogOpen, Tab, View
from ov.browser.pilot import Pilot

OFF_SITE = "Stayed on this page: the browser only opens this site, so it did not go to {urls}."
TABS_NOTE = "Tabs: the page opened more windows. You see the shown one; switch or close them with browser_tab."
LOADING_NOTE = "The page is still loading; wait or look again if parts are missing."
DIALOG_OPEN = (
    'The page is showing a {kind}: "{message}". It waits until the {kind} is answered: answer it with browser_dialog.'
)
SCREENSHOT_NOTE = "Screenshot attached: {width}x{height}; its pixels are the x and y the browser tools take."


def _tabs(tabs: list[Tab]) -> str:
    if len(tabs) < 2:
        return ""
    lines = [f"[{t.index}] {t.title or '(untitled)'} | {t.url}{' (shown)' if t.active else ''}" for t in tabs]
    return f"\n\n{TABS_NOTE}\n" + "\n".join(lines)


def render(view: View) -> str:
    loading = f"\n{LOADING_NOTE}" if view.loading else ""
    return f"{view.title}\n{view.url}\nScreen {view.width}x{view.height}{loading}{_tabs(view.tabs)}\n\n{view.tree}"


def dialog_note(exc: DialogOpen) -> str:
    return DIALOG_OPEN.format(kind=exc.dialog.kind, message=exc.dialog.message)


def attach(ctx: ToolContext, pilot: Pilot) -> bool:
    if not ctx.vision:
        return False
    data = base64.b64encode(pilot.screenshot()).decode()
    ctx.attach_image(f"browser-{serial()}.jpg", f"data:image/jpeg;base64,{data}")
    return True


def result(pilot: Pilot, done: str) -> str:
    title, url = pilot.where()
    lines = [done, f"Now: {title} | {url}"]
    blocked = pilot.take_blocked()
    if blocked:
        lines.append(OFF_SITE.format(urls=", ".join(blocked)))
    return "\n".join(lines) + _tabs(pilot.tabs())


def look(ctx: ToolContext, pilot: Pilot, screenshot: bool) -> str:
    view = pilot.snapshot()
    ctx.browser.saw(f"{view.url}\n{view.tree}")
    page = render(view)
    if not screenshot or not attach(ctx, pilot):
        return page
    return f"{page}\n\n{SCREENSHOT_NOTE.format(width=view.width, height=view.height)}"


def reported(action: Handler) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        done = action(args, ctx)
        return result(ctx.browser.pilot(), done)

    return wrapped


def dialog_aware(handler: Handler) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return handler(args, ctx)
        except DialogOpen as exc:
            return dialog_note(exc)

    return wrapped
