from __future__ import annotations

import argparse

from ov.cli.context import Context
from ov.cli.output import emit, note
from ov.core import update

SHORT = 7
DATABASE_WAITS = (
    "The agent database still needs an upgrade, and a running 'ov agent' has it open. "
    "Stop it and start 'ov agent' again; it upgrades the database on start."
)


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
    return commit[:SHORT]


def cmd_update(ctx: Context) -> int:
    note(ctx, "Checking for updates...")
    found = update.plan()
    data = {
        "current": found.current,
        "latest": found.latest,
        "commits": found.commits,
        "checkout": str(found.install.checkout) if found.install.checkout else None,
    }

    current = found.current == found.latest and not found.reinstall
    if ctx.args.check:
        status = "up_to_date" if current else "available"
        emit(ctx, {**data, "status": status}, text=_up_to_date(found) if current else _available_text(found))
        return 0

    if current:
        migrated = update.migrate()
        emit(ctx, {**data, "status": "up_to_date", "database": migrated}, text=_up_to_date(found, migrated))
        return 0

    note(ctx, _starting_text(found))
    if found.install.checkout is not None and found.current != found.latest:
        note(ctx, f"Pulling into {found.install.checkout}...")
        update.pull(found)

    if found.reinstall:
        note(ctx, "Installing...")
        update.reinstall(update.install_command(found))

    note(ctx, "Upgrading the agent database...")
    migrated = update.migrate()
    emit(ctx, {**data, "status": "updated", "database": migrated}, text=_done_text(found, migrated))
    return 0


def _up_to_date(found: update.Plan, migrated: bool = True) -> str:
    lines = [f"Already up to date ({_short(found.latest)})."]
    if not migrated:
        lines.append(DATABASE_WAITS)
    return "\n".join(lines)


def _available_text(found: update.Plan) -> str:
    lines = [f"Update available: {_short(found.current)} -> {_short(found.latest)}.", *found.commits]
    return "\n".join([*lines, "Run 'ov update' to install it."])


def _starting_text(found: update.Plan) -> str:
    if found.current == found.latest:
        return f"Reinstalling ov {_short(found.current)} to restore missing packages."
    return "\n".join([f"Updating ov {_short(found.current)} -> {_short(found.latest)}:", *found.commits])


def _done_text(found: update.Plan, migrated: bool) -> str:
    lines = [f"[green]ov is now at {_short(found.latest)}.[/green]"]
    if not migrated:
        lines.append(DATABASE_WAITS)
    lines.append("Restart a running 'ov agent' to use the new version.")
    return "\n".join(lines)
