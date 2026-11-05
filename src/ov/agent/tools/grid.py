from __future__ import annotations

import json
import time
from typing import Any

from ov.agent.engine.cancel import Cancel
from ov.agent.engine.files import within
from ov.agent.instances import datasets
from ov.agent.instances.ovproc import find_instance
from ov.agent.tools.base import Tool, ToolContext, ToolError, brief, int_param, mask_secrets, serial, string_param
from ov.agent.tools.onevizion import (
    INSTANCE,
    alias_for,
    check_ov_args,
    masked,
    require_test_sql,
    target_instance,
)

DEFAULT_ROWS = 500
PREVIEW_ROWS = 10
COLUMN_TYPES = ("text", "number", "date", "link", "trackor", "status")
FILE_FLAGS = ("--out", "--file")
SIGN_IN_ATTEMPTS = 2


def _sql_rows(alias: str, source: dict[str, Any], cancel: Cancel) -> tuple[list[dict[str, Any]], int]:
    columns, cells, total = datasets.sql_rows(alias, source["query"], source["limit"], cancel)
    rows = [dict(zip(columns, masked(columns, row), strict=True)) for row in cells]
    return rows, total


def _ov_rows(alias: str, source: dict[str, Any], cancel: Cancel) -> tuple[list[dict[str, Any]], int]:
    found = datasets.ov_records(alias, source["args"], source.get("path") or "", cancel)
    rows = json.loads(mask_secrets(json.dumps(found)))
    return rows[: datasets.MAX_ROWS], len(rows)


def fetch(alias: str, source: dict[str, Any], cancel: Cancel) -> tuple[list[dict[str, Any]], int]:
    if source["kind"] == "sql":
        return _sql_rows(alias, source, cancel)
    return _ov_rows(alias, source, cancel)


def _column(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not str(raw.get("key") or "").strip():
        raise ToolError("Every column needs a key: the name of the field in each row.")

    kind = str(raw.get("type") or "")
    if kind not in COLUMN_TYPES:
        raise ToolError(f"Column {raw['key']} needs a type, one of: {', '.join(COLUMN_TYPES)}.")

    column = {"key": str(raw["key"]), "label": str(raw.get("label") or raw["key"]), "type": kind}
    if kind == "link":
        if not raw.get("href"):
            raise ToolError(f"Link column {raw['key']} needs href, e.g. /admin/rules/Form.do?id={{RULE_ID}}.")
        column["href"] = str(raw["href"])

    if kind == "trackor":
        if not raw.get("id_key"):
            raise ToolError(f"Trackor column {raw['key']} needs id_key: the column that holds the TRACKOR_ID.")
        column["idKey"] = str(raw["id_key"])

    return column


def _check_keys(columns: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    present = set().union(*(row.keys() for row in rows))
    needed = {c["key"] for c in columns} | {c["idKey"] for c in columns if "idKey" in c}
    missing = sorted(needed - present)
    if missing:
        raise ToolError(f"Not in the data: {', '.join(missing)}. The rows have: {', '.join(sorted(present))}.")


def _source(args: dict[str, Any]) -> dict[str, Any] | None:
    given = [key for key in ("sql", "ov", "file", "rows") if args.get(key)]
    if len(given) != 1:
        raise ToolError("Give exactly one of sql, ov, file or rows.")

    if args.get("sql"):
        limit = min(max(int(args.get("limit") or DEFAULT_ROWS), 1), datasets.MAX_ROWS)
        return {"kind": "sql", "query": str(args["sql"]).strip().rstrip(";"), "limit": limit}

    if args.get("ov"):
        ov_args = [str(a) for a in args["ov"]]
        check_ov_args(ov_args, allow_sql=False)
        if any(a.split("=")[0] in FILE_FLAGS for a in ov_args):
            raise ToolError("A grid reads the response directly; leave out --out and --file.")
        return {"kind": "ov", "args": ov_args, "path": str(args.get("path") or "")}

    return None


def _local_rows(args: dict[str, Any], ctx: ToolContext) -> tuple[list[dict[str, Any]], int]:
    if args.get("rows"):
        rows = datasets.records(args["rows"], "")
        return rows[: datasets.MAX_ROWS], len(rows)

    path = within(ctx.work_dir, str(args["file"]))
    if not path.is_file():
        raise ToolError(f"No file {args['file']} in the run folder.")
    rows = datasets.records(json.loads(path.read_text(encoding="utf-8")), str(args.get("path") or ""))
    return rows[: datasets.MAX_ROWS], len(rows)


def _fetched(target: str, source: dict[str, Any], ctx: ToolContext) -> tuple[str, list[dict[str, Any]], int]:
    alias, host, tenant = alias_for(target, ctx)
    for attempt in range(SIGN_IN_ATTEMPTS):
        try:
            rows, total = fetch(alias, source, ctx.cancel)
            return alias, rows, total
        except datasets.SignInNeeded:
            if attempt == SIGN_IN_ATTEMPTS - 1 or not ctx.require_login(host, tenant):
                raise

    raise ToolError(f"Still not signed in to {target}.")


def _preview(columns: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    keys = [c["key"] for c in columns]
    lines = ["\t".join(keys)] + ["\t".join(str(row.get(k, "")) for k in keys) for row in rows[:PREVIEW_ROWS]]
    return "\n".join(lines)


def _grid(args: dict[str, Any], ctx: ToolContext) -> str:
    columns = [_column(c) for c in args.get("columns") or []]
    if not columns:
        raise ToolError("Give the columns to show.")

    source = _source(args)
    try:
        if source is None:
            alias = None
            rows, total = _local_rows(args, ctx)
        else:
            target = target_instance(args.get("instance"), ctx)
            if source["kind"] == "sql":
                require_test_sql(target)
            alias, rows, total = _fetched(target, source, ctx)
    except datasets.DatasetError as exc:
        raise ToolError(str(exc)) from None

    _check_keys(columns, rows)

    found = find_instance(alias or str(args.get("instance") or ctx.instance))
    grid = {
        "id": f"grid_{int(time.time() * 1000)}_{serial()}",
        "title": str(args["title"]),
        "columns": columns,
        "rows": rows,
        "total": total,
        "ranAt": int(time.time() * 1000),
        **({"instance": found["alias"], "baseUrl": found["url"]} if found else {}),
        **({"source": source} if source else {}),
    }
    ctx.emit({"type": "grid", "grid": grid})

    shown = f"{len(rows)} of {total}" if total > len(rows) else str(len(rows))
    return f"Grid shown to the user: {shown} rows. First rows:\n{_preview(columns, rows)}"


COLUMN = {
    "type": "object",
    "properties": {
        "key": string_param("Field name in each row, exactly as in the data (SQL columns are upper case)"),
        "label": string_param("Header text; defaults to the key"),
        "type": {"type": "string", "enum": list(COLUMN_TYPES)},
        "href": string_param(
            "For link columns: a URL or a path on the instance, with {COLUMN} placeholders, "
            "e.g. /admin/rules/Form.do?id={RULE_ID}"
        ),
        "id_key": string_param("For trackor columns: the column holding the TRACKOR_ID the key links to"),
    },
    "required": ["key", "type"],
    "additionalProperties": False,
}

TOOLS = [
    Tool(
        "run_grid",
        "Show data to the user as a grid in the thread, like a OneVizion grid: sortable, filterable, with links. "
        "Use it whenever an answer is a list of records or rows the user wants to see. Give exactly one source: "
        "sql (runs the SELECT itself; the user can re-run it), ov (a read-only ov call returning JSON, with path to "
        "the list; re-runnable), file (a JSON file in the run folder, e.g. one saved with --out) or rows (a few "
        "records you already have). Up to 1000 rows. Typed columns: trackor keys link to their trackor, link "
        "columns to any form.",
        {
            "title": string_param("What the grid shows, a few words"),
            "instance": INSTANCE,
            "columns": {"type": "array", "minItems": 1, "items": COLUMN},
            "sql": string_param("A SELECT to run with Test SQL"),
            "limit": int_param(f"Rows for sql, default {DEFAULT_ROWS}, max {datasets.MAX_ROWS}"),
            "ov": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'ov arguments for a read-only call, e.g. ["request","GET","/v3/imports/runs"]',
            },
            "path": string_param("Dot path to the list of records inside the JSON (ov or file), e.g. data.items"),
            "file": string_param("A JSON file in the run folder"),
            "rows": {"type": "array", "items": {"type": "object"}, "description": "Records to show as they are"},
        },
        ["title", "columns"],
        lambda a: f"grid: {brief(a.get('title', ''))}",
        _grid,
        silent=True,
    ),
]
