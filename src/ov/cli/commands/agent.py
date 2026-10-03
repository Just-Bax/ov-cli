from __future__ import annotations

import argparse

from ..context import Context

DEFAULT_PORT = 5180


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    agent = subparsers.add_parser(
        "agent",
        aliases=["ui"],
        parents=[common],
        help="open the AI agent in your browser (GitHub Copilot powered)",
        description="Start the local agent web app on 127.0.0.1 and open it in your browser.",
    )
    agent.add_argument("--port", type=int, default=DEFAULT_PORT, help="default 5180")
    agent.add_argument("--no-open", action="store_true", help="do not open a browser window")
    agent.set_defaults(func=cmd_agent)


def cmd_agent(ctx: Context) -> int:
    from ...agent.server import serve

    return serve(ctx.args.port, open_browser=not ctx.args.no_open)
