from __future__ import annotations

from typing import Any

from ov.agent.instances import graph
from ov.agent.instances.http import open_client, web_session_alive
from ov.agent.tools.base import (
    REJECTED_WITH_NOTE,
    UI_ONLY,
    Tool,
    ToolContext,
    ToolError,
    brief,
    clip,
    string_param,
)
from ov.agent.tools.onevizion import INSTANCE, alias_for, target_instance
from ov.core.errors import SessionExpired

EXECUTION_PATH = "/admin/plsqlblock/Execution.do"
PLSQL_TIMEOUT_SECONDS = 900.0
BLOCKED = (
    "Blocked: this thread is Read-only, so the PL/SQL block was not run. Do not retry. Show the user the block "
    "and tell them they can switch the thread to Always ask or Auto below the chat if they want it run."
)
REJECTED = "The user rejected this PL/SQL block. Do not retry it; ask what they want instead."
NOT_ENABLED = "ov_plsql is off. OV Agent must be started with: ov agent --allow-plsql"
SIGN_IN_SKIPPED = "{alias} needs a web session sign-in to run PL/SQL, and the user skipped it."
STILL_SIGNED_OUT = "Still no web session for {alias} after the sign-in."
SESSION_ENDED = "The web session for {alias} ended before the block ran. Call ov_plsql again to sign in."

_switch = {"enabled": False}


def enable() -> None:
    _switch["enabled"] = True


def offered() -> list[Tool]:
    return TOOLS if _switch["enabled"] else []


def _require_web_session(signed_in: tuple[str, str, str], ctx: ToolContext) -> None:
    alias, host, tenant = signed_in
    if web_session_alive(alias):
        return

    if not ctx.require_login(host, tenant, web=True):
        raise ToolError(SIGN_IN_SKIPPED.format(alias=alias))

    if not web_session_alive(alias):
        raise ToolError(STILL_SIGNED_OUT.format(alias=alias))


def _execute(alias: str, block: str) -> str:
    with open_client(alias) as client:
        response = client.web_post_form(
            EXECUTION_PATH, {"plsql": block, "isHandleOutput": "true"}, PLSQL_TIMEOUT_SECONDS
        )
        return response.text


def _plsql(args: dict[str, Any], ctx: ToolContext) -> str:
    if not _switch["enabled"]:
        raise ToolError(NOT_ENABLED)

    block = str(args.get("block") or "").strip()
    purpose = " ".join(str(args.get("purpose") or "").split())
    if not block or not purpose:
        raise ToolError("Give the PL/SQL block and its purpose.")

    if not ctx.can_write():
        raise ToolError(BLOCKED)

    if ctx.browser.live:
        raise ToolError(UI_ONLY)

    signed_in = alias_for(target_instance(args.get("instance"), ctx), ctx)
    _require_web_session(signed_in, ctx)
    approval = ctx.ask_approval(f"Run this PL/SQL block on {signed_in[1]}? {purpose}", block)
    if not approval.approved:
        raise ToolError(REJECTED_WITH_NOTE.format(note=approval.note) if approval.note else REJECTED)

    try:
        output = _execute(signed_in[0], block)
    except SessionExpired:
        raise ToolError(SESSION_ENDED.format(alias=signed_in[0])) from None
    finally:
        graph.note_write(signed_in[0])

    return clip(output or "The block ran and printed nothing.", ctx, "PL/SQL output")


TOOLS = [
    Tool(
        "ov_plsql",
        "Run an anonymous PL/SQL block on a OneVizion instance, the way Admin > PL/SQL Block does, and return what "
        "it printed with dbms_output. Use it for changes the API cannot make in one step: enabling or disabling "
        "rules and automations, backfills, data fixes. Every call waits for the user to approve the exact block, "
        "in every access mode, and it is blocked in a Read-only thread. Read first with ov_sql, keep each block "
        "to one purpose, print what it changed (counts, ids), and follow the plsql-best-practices skill. It always "
        "runs in the foreground so the user can approve it; for a long block the user can move it to the background "
        "once it runs.",
        {
            "instance": INSTANCE,
            "purpose": string_param("What the block does, one short sentence the user reads before approving"),
            "block": string_param("The full anonymous block, from declare or begin to end;"),
        },
        ["purpose", "block"],
        lambda a: brief(f"PL/SQL{' @ ' + a['instance'] if a.get('instance') else ''}: {a.get('purpose', '')}"),
        _plsql,
        background=False,
    ),
]
