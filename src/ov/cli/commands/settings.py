from __future__ import annotations

import argparse

from ... import config as config_module
from ... import session
from ...paths import cache_dir, config_file, downloads_dir, home, spec_dir
from ..context import Context
from ..output import build_table, emit


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    group = subparsers.add_parser("config", parents=[common], help="show or change settings")
    actions = group.add_subparsers(dest="action")

    show = actions.add_parser("show", parents=[common], help="print the effective settings")
    show.set_defaults(func=cmd_show)

    set_cmd = actions.add_parser("set", parents=[common], help="change one setting")
    set_cmd.add_argument("key", help="setting name")
    set_cmd.add_argument("value", help="new value")
    set_cmd.set_defaults(func=cmd_set)

    clear = actions.add_parser("clear-cache", parents=[common], help="drop cached API responses")
    clear.set_defaults(func=cmd_clear_cache)

    group.set_defaults(func=cmd_show)


def _payload(ctx: Context) -> dict[str, object]:
    # Declared settings only, so the token and cookies sharing this file are
    # never echoed here.
    data = ctx.config.to_dict()
    data["current_instance"] = session.current_alias()
    data["instances"] = sorted(session.all_sessions())
    data["paths"] = {
        "home": str(home()),
        "config": str(config_file()),
        "spec": str(spec_dir()),
        "cache": str(cache_dir()),
        "downloads": str(ctx.config.resolved_download_dir()),
        "default_downloads": str(downloads_dir()),
    }
    return data


def cmd_show(ctx: Context) -> int:
    data = _payload(ctx)

    def table():
        rows = [[k, str(v)] for k, v in data.items() if k != "paths"]
        rows += [[f"paths.{k}", v] for k, v in data["paths"].items()]
        return build_table(
            None, [{"header": "Setting", "style": "cyan"}, {"header": "Value"}], rows
        )

    emit(ctx, data, table)
    return 0


def cmd_set(ctx: Context) -> int:
    ctx.config = config_module.set_value(ctx.config, ctx.args.key, ctx.args.value)
    data = {"key": ctx.args.key, "value": getattr(ctx.config, ctx.args.key)}

    emit(
        ctx,
        data,
        lambda: build_table(
            None,
            [{"header": "Setting", "style": "cyan"}, {"header": "Value"}],
            [[ctx.args.key, str(data["value"])]],
        ),
    )
    return 0


def cmd_clear_cache(ctx: Context) -> int:
    removed = ctx.cache.clear()
    emit(ctx, {"cache_entries_cleared": removed}, text=f"Cleared {removed} cached response(s).")
    return 0
