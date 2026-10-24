from __future__ import annotations

import argparse

from ov.cli.context import Context
from ov.cli.output import emit
from ov.core import update

DEFAULT_PORT = 5180


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    agent = subparsers.add_parser(
        "agent",
        aliases=["ui"],
        parents=[common],
        help="open the AI agent in your browser",
        description="Start the local agent web app on 127.0.0.1 and open it in your browser.",
    )
    agent.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"default {DEFAULT_PORT}")
    agent.add_argument("--no-open", action="store_true", help="do not open a browser window")
    agent.add_argument("--migrate", action="store_true", help="upgrade the agent database and exit")
    agent.add_argument(
        "--full-access",
        action="store_true",
        help="offer Full access: threads set to it make every change without asking",
    )
    agent.set_defaults(func=cmd_agent)


def cmd_agent(ctx: Context) -> int:
    update.require_dependencies()
    from ov.agent.api.server import serve
    from ov.agent.instances.forget import prune
    from ov.agent.storage import db

    if ctx.args.migrate:
        upgraded = db.migrate()
        emit(ctx, {"upgraded": upgraded}, text="Agent database upgraded." if upgraded else "Agent database is current.")
        return 0

    prune()
    return serve(ctx.args.port, open_browser=not ctx.args.no_open, full_access=ctx.args.full_access)
