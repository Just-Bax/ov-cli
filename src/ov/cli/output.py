from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.json import JSON
from rich.table import Table

from ov.cli.context import Context

TABLE_ROW_LIMIT = 200
TABLE_MAX_COLUMNS = 12
CELL_LIMIT = 120

_TableBuilder = Callable[[], Table]


def console(ctx: Context, stderr: bool = False) -> Console:
    return Console(stderr=stderr, no_color=not ctx.use_color, soft_wrap=True)


def emit(
    ctx: Context,
    data: Any,
    table: _TableBuilder | None = None,
    empty: str = "",
    text: str | None = None,
) -> None:
    if ctx.as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return

    out = console(ctx)

    if text is not None:
        out.print(text)
        return

    if not data and empty:
        out.print(empty)
        return

    if table is not None:
        out.print(table())
        return

    emit_payload(ctx, data)


def emit_payload(ctx: Context, payload: Any) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if ctx.as_json:
        print(rendered)
        return

    if isinstance(payload, str):
        console(ctx).print(payload)
        return

    console(ctx).print(JSON(rendered))


def note(ctx: Context, message: str) -> None:
    if not ctx.as_json:
        console(ctx).print(message)


def warn(ctx: Context, message: str) -> None:
    if not ctx.as_json:
        console(ctx, stderr=True).print(message)


def build_table(title: str | None, columns: list[dict[str, Any]], rows: list[list[str]]) -> Table:
    table = Table(title=title, title_justify="left")
    for column in columns:
        table.add_column(**column)
    for row in rows:
        table.add_row(*row)
    return table


def rows_from(payload: Any) -> Table | None:
    if not isinstance(payload, list):
        return None

    if not payload:
        return build_table(None, [{"header": "no rows"}], [])

    if not all(isinstance(item, dict) for item in payload):
        return None

    shown = payload[:TABLE_ROW_LIMIT]
    columns = list(dict.fromkeys(key for item in shown for key in item))
    if not columns or len(columns) > TABLE_MAX_COLUMNS:
        return None

    rows = [[_cell(item.get(column)) for column in columns] for item in shown]
    return build_table(None, [{"header": c, "overflow": "fold"} for c in columns], rows)


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)[:CELL_LIMIT]
    return str(value)
