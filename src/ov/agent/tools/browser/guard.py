from __future__ import annotations

from urllib.parse import urlsplit

from ov.agent.engine.guard import Effect
from ov.agent.tools.base import ToolContext, ToolError, approved
from ov.browser.pilot import Pilot

GUARD_TEXT_CHARS = 200
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
        "heading",
        "option",
    }
)
CHANGING_DIALOGS = frozenset({"confirm", "prompt", "beforeunload"})

BLOCKED = (
    "Blocked: {reason}. This would change something and the thread is Read-only. Do not try another way to do it; "
    "report that it needs changes allowed (Ask first or Auto, not Read-only)."
)
REJECTED = "The user rejected this: {say}. Do not retry it."


def check(ctx: ToolContext, pilot: Pilot, action: str, say: str) -> None:
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
