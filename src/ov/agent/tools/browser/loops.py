from __future__ import annotations

import json
from typing import Any

from ov.agent.engine.browsing import loop_span
from ov.agent.tools.base import Handler, ToolContext, ToolError

SNAPSHOT_TOOL = "browser_snapshot"
REPEATABLE = frozenset({"browser_snapshot", "browser_wait", "browser_press", "browser_scroll"})

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


def _unsaid(args: dict[str, Any]) -> dict[str, Any]:
    plain = {k: v for k, v in args.items() if k != "say"}
    if isinstance(plain.get("steps"), list):
        plain["steps"] = [_unsaid(step) if isinstance(step, dict) else step for step in plain["steps"]]
    return plain


def loop_error(name: str, period: int) -> ToolError:
    count = loop_span(period)
    if period > 1:
        return ToolError(LOOPED.format(count=count, period=period))
    if name == SNAPSHOT_TOOL:
        return ToolError(SAME_PAGE.format(count=count))
    return ToolError(REPEATED.format(name=name, count=count))


def not_repeated(name: str, handler: Handler) -> Handler:
    if name in REPEATABLE:
        return handler

    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        period = ctx.browser.looping(json.dumps({"tool": name, **_unsaid(args)}, sort_keys=True))
        if period:
            raise loop_error(name, period)
        return handler(args, ctx)

    return wrapped
