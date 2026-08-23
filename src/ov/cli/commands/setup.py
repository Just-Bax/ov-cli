from __future__ import annotations

import argparse

from ...login import browser_is_installed, install_chromium
from ..context import Context
from ..output import emit, note


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    group = subparsers.add_parser(
        "setup", parents=[common], help="download the browser needed for signing in"
    )
    group.add_argument("--check", action="store_true", help="report readiness without downloading")
    group.set_defaults(func=cmd_setup)


def cmd_setup(ctx: Context) -> int:
    if browser_is_installed():
        emit(ctx, {"browser": "installed", "ready": True}, text="[green]Ready.[/green] ov login")
        return 0

    if ctx.args.check:
        emit(
            ctx,
            {"browser": "missing", "ready": False},
            text="Browser not installed. Run: ov setup",
        )
        return 1

    note(ctx, "Downloading the browser used for signing in (about 150MB, one time)...")
    if not install_chromium():
        emit(
            ctx,
            {"browser": "failed", "ready": False},
            text="[red]Download failed.[/red] Check your connection and run 'ov setup' again.",
        )
        return 1

    emit(ctx, {"browser": "installed", "ready": True}, text="[green]Ready.[/green] ov login")
    return 0
