from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ov.agent.engine.files import within
from ov.agent.instances.http import open_client
from ov.agent.instances.ovproc import url_for
from ov.agent.tools.base import (
    UI_ONLY,
    Tool,
    ToolContext,
    ToolError,
    approved,
    brief,
    serial,
    string_param,
)
from ov.agent.tools.onevizion import INSTANCE, alias_for, target_instance, with_sign_in
from ov.core.errors import OvError
from ov.onevizion.client import Client

KEY_FIELD = "TRACKOR_KEY"
ID_FIELD = "TRACKOR_ID"
READ_WORKERS = 8
WRITE_WORKERS = 4
PROGRESS_EVERY_SECONDS = 1.0
LISTED_ERRORS = 20
ERROR_CHARS = 300
RECORD_SUFFIX = ".change.json"
BLOCKED = (
    "Blocked: this thread is Read-only, so the change was only shown. Do not retry. Tell the user they can switch "
    "the thread to Always ask or Auto below the chat if they want it applied."
)
REJECTED = "The user rejected this change. Do not retry it."

PROPOSED, RUNNING, DONE, REJECTED_STATE, BLOCKED_STATE, STOPPED = (
    "proposed",
    "running",
    "done",
    "rejected",
    "blocked",
    "stopped",
)
UPDATED, FAILED, UNCHANGED, NOT_RUN = "updated", "failed", "unchanged", "not run"


def _same(before: Any, after: Any) -> bool:
    return ("" if before is None else str(before)) == ("" if after is None else str(after))


def _planned(args: dict[str, Any], ctx: ToolContext) -> list[dict[str, Any]]:
    raw = args.get("rows")
    if args.get("rows_file"):
        path = within(ctx.work_dir, str(args["rows_file"]))
        if not path.is_file():
            raise ToolError(f"No file {args['rows_file']} in the run folder.")
        raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, list) or not raw:
        raise ToolError("Give the rows to change: [{trackor_id, fields: {FIELD: new value}}], inline or in rows_file.")

    planned = []
    for row in raw:
        if not isinstance(row, dict) or not str(row.get("trackor_id") or "").isdigit() or not row.get("fields"):
            raise ToolError("Every row needs trackor_id (a number) and fields (an object of new values).")
        planned.append({"id": int(row["trackor_id"]), "after": dict(row["fields"])})

    return planned


def _record_path(ctx: ToolContext, grid_id: str) -> Path:
    return within(ctx.work_dir, f"{grid_id}{RECORD_SUFFIX}")


def _reverted(grid_id: str, ctx: ToolContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = _record_path(ctx, grid_id)
    if not path.is_file():
        raise ToolError(f"No finished data change {grid_id} in this thread.")

    record = json.loads(path.read_text(encoding="utf-8"))
    rows = [{"id": row["id"], "after": row["before"]} for row in record["rows"] if row["status"] == UPDATED]
    if not rows:
        raise ToolError(f"Data change {grid_id} updated nothing, so there is nothing to revert.")
    return record, rows


def _read_one(client: Client, trackor_id: int, fields: list[str]) -> dict[str, Any]:
    names = ",".join(dict.fromkeys([KEY_FIELD, *fields]))
    found = client.api("GET", f"/v3/trackors/{trackor_id}", params=[("fields", names)]).json()
    if not found:
        raise ToolError(f"Trackor {trackor_id} was not found, or you cannot read it.")
    return found


def _current(alias: str, planned: list[dict[str, Any]], fields: list[str]) -> dict[int, dict[str, Any]]:
    with open_client(alias) as client, ThreadPoolExecutor(max_workers=READ_WORKERS) as pool:
        found = pool.map(lambda row: _read_one(client, row["id"], fields), planned)
        return {row["id"]: current for row, current in zip(planned, found, strict=True)}


def _rows(planned: list[dict[str, Any]], current: dict[int, dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    rows = []
    for plan in planned:
        now = current[plan["id"]]
        cells = {f: {"before": now.get(f), "after": plan["after"][f]} for f in fields if f in plan["after"]}
        changed = any(not _same(c["before"], c["after"]) for c in cells.values())
        rows.append(
            {
                ID_FIELD: plan["id"],
                KEY_FIELD: now.get(KEY_FIELD) or str(plan["id"]),
                **cells,
                "_status": "" if changed else UNCHANGED,
            }
        )

    return rows


def _columns(trackor_type: str, fields: list[str]) -> list[dict[str, Any]]:
    key = {"key": KEY_FIELD, "label": trackor_type, "type": "trackor", "idKey": ID_FIELD}
    return [key, *({"key": f, "label": f, "type": "change"} for f in fields)]


class _Progress:
    def __init__(self, ctx: ToolContext, grid_id: str, change: dict[str, Any]) -> None:
        self.ctx, self.grid_id, self.change = ctx, grid_id, change
        self.lock = threading.Lock()
        self.shown = 0.0

    def count(self, status: str) -> None:
        with self.lock:
            self.change["done"] += 1
            if status == FAILED:
                self.change["failed"] += 1
            else:
                self.change["updated"] += 1
            due = time.monotonic() - self.shown >= PROGRESS_EVERY_SECONDS
            if due:
                self.shown = time.monotonic()
                self.ctx.emit({"type": "grid", "grid": {"id": self.grid_id, "change": dict(self.change)}})


def _apply_one(client: Client, row: dict[str, Any], fields: list[str], ctx: ToolContext, progress: _Progress) -> None:
    if ctx.cancel.is_set():
        row["_status"] = NOT_RUN
        return

    body = {f: row[f]["after"] for f in fields if f in row}
    try:
        client.api("PUT", f"/v3/trackors/{row[ID_FIELD]}", json=body)
        row["_status"] = UPDATED
    except OvError as exc:
        row["_status"], row["_error"] = FAILED, str(exc)[:ERROR_CHARS]

    progress.count(row["_status"])


def _apply(alias: str, rows: list[dict[str, Any]], fields: list[str], ctx: ToolContext, progress: _Progress) -> None:
    pending = [row for row in rows if row["_status"] != UNCHANGED]
    with open_client(alias) as client, ThreadPoolExecutor(max_workers=WRITE_WORKERS) as pool:
        for future in [pool.submit(_apply_one, client, row, fields, ctx, progress) for row in pending]:
            future.result()


def _save(ctx: ToolContext, grid: dict[str, Any], fields: list[str]) -> None:
    rows = grid["rows"]
    record = {
        "title": grid["title"],
        "instance": grid["instance"],
        "trackorType": grid["change"]["trackorType"],
        "rows": [
            {
                "id": row[ID_FIELD],
                "status": row["_status"],
                "before": {f: row[f]["before"] for f in fields if f in row},
            }
            for row in rows
        ],
    }
    _record_path(ctx, grid["id"]).write_text(json.dumps(record), encoding="utf-8")


def _summary(change: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    failed = [row for row in rows if row["_status"] == FAILED]
    lines = [f"- {row[KEY_FIELD]} ({row[ID_FIELD]}): {row['_error']}" for row in failed[:LISTED_ERRORS]]
    more = f"\n... and {len(failed) - LISTED_ERRORS} more" if len(failed) > LISTED_ERRORS else ""
    head = (
        f"{change['updated']} updated, {change['failed']} failed, {change['unchanged']} already had these values"
        + (", stopped before the rest" if change["state"] == STOPPED else "")
        + "."
    )
    return head + ("\nFailures:\n" + "\n".join(lines) + more if lines else "")


def _plan(args: dict[str, Any], ctx: ToolContext) -> tuple[str, str, str, list[dict[str, Any]]]:
    revert_of = str(args.get("revert") or "").strip()
    if revert_of:
        record, planned = _reverted(revert_of, ctx)
        return record["instance"], record["trackorType"], f"Revert: {record['title']}", planned

    trackor_type = str(args.get("trackor_type") or "").strip()
    if not trackor_type:
        raise ToolError("Give trackor_type.")

    planned = _planned(args, ctx)
    title = str(args.get("title") or f"Update {trackor_type}")
    return target_instance(args.get("instance"), ctx), trackor_type, title, planned


def _proposal(
    signed_in: tuple[str, str, str], trackor_type: str, title: str, rows: list[dict[str, Any]], revert_of: str
) -> dict[str, Any]:
    alias, host, _ = signed_in
    fields = list(dict.fromkeys(k for row in rows for k in row if k not in (ID_FIELD, KEY_FIELD, "_status")))
    unchanged = sum(1 for row in rows if row["_status"] == UNCHANGED)
    change = {
        "state": PROPOSED,
        "trackorType": trackor_type,
        "fields": fields,
        "total": len(rows) - unchanged,
        "done": 0,
        "updated": 0,
        "failed": 0,
        "unchanged": unchanged,
        **({"revertOf": revert_of} if revert_of else {}),
    }
    return {
        "id": f"grid_{int(time.time() * 1000)}_{serial()}",
        "title": title,
        "instance": alias,
        "baseUrl": url_for(host),
        "columns": _columns(trackor_type, fields),
        "rows": rows,
        "total": len(rows),
        "ranAt": int(time.time() * 1000),
        "change": change,
    }


def _settle(ctx: ToolContext, grid: dict[str, Any], state: str) -> None:
    grid["change"]["state"] = state
    ctx.emit({"type": "grid", "grid": {"id": grid["id"], "change": dict(grid["change"])}})


def _confirm(ctx: ToolContext, grid: dict[str, Any]) -> None:
    change = grid["change"]
    if not ctx.can_write():
        _settle(ctx, grid, BLOCKED_STATE)
        raise ToolError(BLOCKED)

    if ctx.browser.live:
        raise ToolError(UI_ONLY)

    question = f"Update {change['total']} {change['trackorType']} trackors on {grid['instance']}?"
    detail = f"Fields: {', '.join(change['fields'])}. Every change is in the grid above."
    if not approved(ctx, question, detail):
        _settle(ctx, grid, REJECTED_STATE)
        raise ToolError(REJECTED)


def _update(args: dict[str, Any], ctx: ToolContext) -> str:
    target, trackor_type, title, planned = _plan(args, ctx)
    fields = list(dict.fromkeys(f for row in planned for f in row["after"]))
    signed_in = alias_for(target, ctx)
    current = with_sign_in(signed_in, ctx, lambda a: _current(a, planned, fields))

    grid = _proposal(signed_in, trackor_type, title, _rows(planned, current, fields), str(args.get("revert") or ""))
    ctx.emit({"type": "grid", "grid": grid})
    if not grid["change"]["total"]:
        _settle(ctx, grid, DONE)
        return f"Nothing to change: all {grid['total']} trackors already have these values."

    _confirm(ctx, grid)
    _settle(ctx, grid, RUNNING)
    progress = _Progress(ctx, grid["id"], grid["change"])
    with_sign_in(signed_in, ctx, lambda a: _apply(a, grid["rows"], fields, ctx, progress))

    stopped = any(row["_status"] == NOT_RUN for row in grid["rows"])
    grid["change"]["state"] = STOPPED if stopped else DONE
    _save(ctx, grid, fields)
    ctx.emit({"type": "grid", "grid": {"id": grid["id"], "rows": grid["rows"], "change": grid["change"]}})
    return f"Data change {grid['id']}: {_summary(grid['change'], grid['rows'])}"


TOOLS = [
    Tool(
        "ov_update",
        "Change field values on many trackors at once, shown to the user as a grid with the old and new value of "
        "every cell before anything is written. It reads the current values itself, skips trackors that already "
        "have the new values, then asks for approval like any change and writes each trackor through the API. "
        "Afterwards the grid shows which rows failed and why. Find the trackors first (ov_search, run_grid or "
        "ov_sql). Values use the API format: drop-down text, dates as YYYY-MM-DD. To undo a finished change, call "
        "it with revert and the grid id.",
        {
            "instance": INSTANCE,
            "title": string_param("What the change does, a few words"),
            "trackor_type": string_param("Trackor type name of every trackor in rows"),
            "rows": {
                "type": "array",
                "description": "One entry per trackor",
                "items": {
                    "type": "object",
                    "properties": {
                        "trackor_id": {"type": "integer", "description": "TRACKOR_ID"},
                        "fields": {"type": "object", "description": "Field name to new value"},
                    },
                    "required": ["trackor_id", "fields"],
                    "additionalProperties": False,
                },
            },
            "rows_file": string_param("Instead of rows: a JSON file in the run folder with the same list"),
            "revert": string_param("Grid id of a finished data change to undo; then give nothing else"),
        },
        [],
        lambda a: brief(f"update {a.get('trackor_type') or 'revert ' + str(a.get('revert'))}: {a.get('title', '')}"),
        _update,
        silent=True,
    ),
]
