from __future__ import annotations

import argparse

from ... import update
from ..context import Context
from ..output import emit, note

SHORT = 7


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    group = subparsers.add_parser(
        "update",
        parents=[common],
        help="update ov to the latest version from GitHub",
        description="Fetch the latest ov with git (your own GitHub access) and install it.",
    )
    group.add_argument("--check", action="store_true", help="only report whether an update is available")
    group.set_defaults(func=cmd_update)


def _short(commit: str) -> str:
    return commit[:SHORT] if commit else "unknown"


def cmd_update(ctx: Context) -> int:
    note(ctx, "Checking GitHub for the latest version...")
    found = update.plan()
    data = {
        "current": found.current or None,
        "latest": found.latest,
        "commits": found.commits,
        "checkout": str(found.install.checkout) if found.install.checkout else None,
    }
    if found.current == found.latest:
        emit(ctx, {**data, "status": "up_to_date"}, text=f"Already up to date ({_short(found.latest)}).")
        return 0

    if ctx.args.check:
        emit(ctx, {**data, "status": "available"}, text=_available_text(found))
        return 0

    if found.install.checkout is not None:
        note(ctx, f"Pulling into {found.install.checkout}...")
        update.pull(found)

    finishing = update.reinstall(update.install_command(found)) if found.reinstall else False
    emit(ctx, {**data, "status": "updating" if finishing else "updated"}, text=_done_text(found, finishing))
    return 0


def _available_text(found: update.Plan) -> str:
    lines = [f"Update available: {_short(found.current)} -> {_short(found.latest)}.", *found.commits]
    return "\n".join([*lines, "Run 'ov update' to install it."])


def _done_text(found: update.Plan, finishing: bool) -> str:
    lines = [f"[green]Updated[/green] {_short(found.current)} -> {_short(found.latest)}.", *found.commits]
    if finishing:
        lines.append(
            f"Reinstalling in the background; it finishes a few seconds after this command exits "
            f"(log: {update.log_file()})."
        )
    lines.append("Restart a running 'ov agent' to use the new version.")
    return "\n".join(lines)
