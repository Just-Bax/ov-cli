from __future__ import annotations

import json
import re
from typing import Any

from ov.agent.instances import access
from ov.agent.instances.http import open_client
from ov.agent.instances.ovproc import instances
from ov.agent.tools.base import (
    UI_ONLY,
    Tool,
    ToolContext,
    ToolError,
    approved,
    brief,
    clip,
    serial,
    string_param,
)
from ov.agent.tools.onevizion import INSTANCE, alias_for, target_instance, with_sign_in

MCP_PATH = "/ai/mcp"
JSON_RPC = "2.0"
DESCRIPTION_CHARS = 400
WRITE_TOOL = re.compile(r"(create|update|delete|set_as_current)", re.IGNORECASE)
NO_MCP = (
    "Your account on {instance} cannot use the platform's MCP server: it needs an AI Enabled instance and the "
    "MCP_SERVER privilege. Use ov, ov_search and ov_export instead."
)
CHECK_NAME = "Use a tool name exactly as listed: call ov_mcp without tool to list the tools and their arguments."
BLOCKED = (
    "Blocked: this MCP tool changes data and this thread is Read-only. Do not retry; tell the user what it would do."
)


def offered() -> list[Tool]:
    return TOOLS if any(access.allows(row["alias"], "mcp") for row in instances()) else []


def _rpc(alias: str, method: str, params: dict[str, Any]) -> Any:
    message = {"jsonrpc": JSON_RPC, "id": serial(), "method": method, "params": params}
    with open_client(alias) as client:
        body = client.post_json(MCP_PATH, message).json()

    if body.get("error"):
        refused = f"The MCP server refused {method}: {body['error'].get('message') or body['error']}"
        raise ToolError(f"{refused} {CHECK_NAME}" if method == "tools/call" else refused)
    return body["result"]


def _listing(result: dict[str, Any]) -> str:
    lines = []
    for tool in result.get("tools") or []:
        params = ", ".join((tool.get("inputSchema") or {}).get("properties") or {})
        about = " ".join(str(tool.get("description") or "").split())[:DESCRIPTION_CHARS]
        lines.append(f"- {tool['name']}({params}): {about}")
    return "MCP tools:\n" + "\n".join(lines)


def _called(result: dict[str, Any]) -> str:
    text = "\n".join(str(part.get("text") or json.dumps(part)) for part in result.get("content") or [])
    if result.get("isError"):
        raise ToolError(f"The MCP tool failed: {text}")
    return text or "(no content)"


def _check_write(name: str, arguments: dict[str, Any], alias: str, ctx: ToolContext) -> None:
    if not WRITE_TOOL.search(name):
        return

    if not ctx.can_write():
        raise ToolError(BLOCKED)
    if ctx.browser.live:
        raise ToolError(UI_ONLY)
    if not approved(ctx, f"Run the MCP tool {name} on {alias}?", json.dumps(arguments, indent=2)):
        raise ToolError("The user rejected this change. Do not retry it.")


def _mcp(args: dict[str, Any], ctx: ToolContext) -> str:
    signed_in = alias_for(target_instance(args.get("instance"), ctx), ctx)
    alias = signed_in[0]
    if access.allows(alias, "mcp") is False:
        raise ToolError(NO_MCP.format(instance=alias))

    name = str(args.get("tool") or "").strip()
    if not name:
        return clip(_listing(with_sign_in(signed_in, ctx, lambda a: _rpc(a, "tools/list", {}))), ctx, "tool list")

    arguments = args.get("arguments") or {}
    _check_write(name, arguments, alias, ctx)
    params = {"name": name, "arguments": arguments}
    return clip(_called(with_sign_in(signed_in, ctx, lambda a: _rpc(a, "tools/call", params))), ctx, "MCP result")


TOOLS = [
    Tool(
        "ov_mcp",
        "Use the instance's own MCP server (AI Enabled instances only): leave tool out to list its tools, then call "
        "one by name with its arguments. Good for schema summaries with relations, trackor search, views, filters, "
        "workplans and tasks. Tools that create, update or delete wait for approval like any change.",
        {
            "instance": INSTANCE,
            "tool": string_param("MCP tool name; leave out to list the tools"),
            "arguments": {
                "type": "object",
                "description": "Every argument of the MCP tool goes in here, as its schema says",
            },
        },
        [],
        lambda a: brief(f"mcp {a.get('tool') or 'tools'}{' @ ' + a['instance'] if a.get('instance') else ''}"),
        _mcp,
    ),
]
