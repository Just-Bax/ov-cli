from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.json import JSON
from rich.table import Table

from .context import Context

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
    """Single decision point for how a command's result reaches the user:
    commands build data and describe how to show it, nothing else prints."""
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
    """Print an API response.

    Both modes print JSON: --json stays byte-for-byte pipeable, while the human
    mode adds highlighting. A response that was never JSON is printed as it came.
    """
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if ctx.as_json:
        print(rendered)
        return
    if isinstance(payload, str):
        console(ctx).print(payload)
        return
    console(ctx).print(JSON(rendered))


def note(ctx: Context, message: str) -> None:
    """Human-facing progress or status text, suppressed in JSON mode."""
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


def rows_from(payload: Any, limit: int = 200) -> Table | None:
    """Render a list of flat objects as a table, or give up so the caller falls
    back to JSON."""
    if not isinstance(payload, list) or not payload:
        return None
    if not all(isinstance(item, dict) for item in payload):
        return None

    columns: list[str] = []
    for item in payload[:limit]:
        for key in item:
            if key not in columns:
                columns.append(key)
    if not columns or len(columns) > 12:
        return None

    rows = [[_cell(item.get(column)) for column in columns] for item in payload[:limit]]
    return build_table(None, [{"header": c, "overflow": "fold"} for c in columns], rows)


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)[:120]
    return str(value)
