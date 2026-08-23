from __future__ import annotations

import argparse
import json
from datetime import datetime

from ... import spec as spec_module
from ..context import Context
from ..output import build_table, emit


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    group = subparsers.add_parser(
        "spec",
        parents=[common],
        help="manage the cached OpenAPI schema that the generated commands come from",
    )
    actions = group.add_subparsers(dest="action")

    show = actions.add_parser("show", parents=[common], help="summarise the cached schema")
    show.set_defaults(func=cmd_show)

    fetch = actions.add_parser("fetch", parents=[common], help="download the schema again")
    fetch.set_defaults(func=cmd_fetch)

    groups = actions.add_parser("groups", parents=[common], help="list schema groups on the server")
    groups.set_defaults(func=cmd_groups)

    dump = actions.add_parser("dump", parents=[common], help="print the raw OpenAPI document")
    dump.set_defaults(func=cmd_dump)

    group.set_defaults(func=cmd_show)


def cmd_show(ctx: Context) -> int:
    spec = ctx.service.spec(refresh=ctx.refresh)
    data = spec.to_dict()
    data["cached_at"] = _stamp(spec.fetched_at)
    data["path"] = str(spec_module.cached_path(ctx.service.base_url, ctx.config.spec_group))

    def table():
        rows = [[k, str(v)] for k, v in data.items() if k != "tags"]
        rows.append(["tags", ", ".join(spec.tags)])
        return build_table(
            None,
            [{"header": "Field", "style": "cyan"}, {"header": "Value", "overflow": "fold"}],
            rows,
        )

    emit(ctx, data, table)
    return 0


def cmd_fetch(ctx: Context) -> int:
    spec = ctx.service.fetch_spec()
    path = spec_module.cached_path(ctx.service.base_url, ctx.config.spec_group)
    data = {
        "group": spec.group,
        "operations": len(spec.operations),
        "tags": len(spec.tags),
        "path": str(path),
    }
    emit(
        ctx,
        data,
        text=f"[green]Fetched[/green] {len(spec.operations)} operations "
        f"in {len(spec.tags)} tags -> {path}",
    )
    return 0


def cmd_groups(ctx: Context) -> int:
    names = ctx.service.spec_groups()
    emit(
        ctx,
        names,
        lambda: build_table(None, [{"header": "Group", "style": "cyan"}], [[n] for n in names]),
        empty="No schema groups reported.",
    )
    return 0


def cmd_dump(ctx: Context) -> int:
    ctx.service.spec(refresh=ctx.refresh)
    document = spec_module.raw_document(ctx.service.base_url, ctx.config.spec_group)
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0


def _stamp(epoch: float) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch).isoformat(timespec="seconds")
