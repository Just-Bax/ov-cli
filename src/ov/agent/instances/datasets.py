from __future__ import annotations

import json
from typing import Any

from ov.agent.engine.cancel import Cancel
from ov.agent.instances.graph import SQL_REQUEST
from ov.agent.instances.ovproc import OvResult, run_ov
from ov.core.errors import EXIT_READ_ONLY

SQL_TIMEOUT_SECONDS = 300
OV_TIMEOUT_SECONDS = 180
MAX_ROWS = 1000
ERROR_CHARS = 600
SQL_FAILED = "FAILED"


class DatasetError(Exception):
    pass


class SignInNeeded(DatasetError):
    pass


def _checked(result: OvResult, alias: str) -> str:
    if result.is_auth:
        raise SignInNeeded(f"The session for {alias} expired. Sign in again.")
    if result.timed_out:
        raise DatasetError(f"{alias} did not answer in time.")
    if result.code == EXIT_READ_ONLY:
        raise DatasetError("A grid only reads data; this call would change something.")
    if result.code != 0:
        raise DatasetError(result.message[:ERROR_CHARS] or f"ov exited {result.code}")
    return result.stdout


def sql_rows(alias: str, query: str, limit: int, cancel: Cancel) -> tuple[list[str], list[list[Any]], int]:
    size = min(max(limit, 1), MAX_ROWS)
    result = run_ov(
        ["-i", alias, *SQL_REQUEST, "-q", f"rows_count={size}", "-d", query, "--json"],
        timeout=SQL_TIMEOUT_SECONDS,
        cancel=cancel,
    )
    parsed = json.loads(_checked(result, alias))
    if parsed.get("status") == SQL_FAILED:
        raise DatasetError(f"SQL failed: {parsed.get('error_message') or 'no message'}")

    rows = [row["cells"] for row in parsed["rows"]]
    return parsed["columns"], rows, int(parsed.get("total_rows") or len(rows))


def _at_path(data: Any, path: str) -> Any:
    for part in [p for p in path.split(".") if p]:
        if not isinstance(data, dict) or part not in data:
            raise DatasetError(f"The response has no {part!r} at {path!r}.")
        data = data[part]
    return data


def records(data: Any, path: str) -> list[dict[str, Any]]:
    found = _at_path(data, path)
    if not isinstance(found, list) or not all(isinstance(row, dict) for row in found):
        where = f" at {path!r}" if path else ""
        raise DatasetError(f"Expected a list of records{where}; give path to the list inside the response.")
    return found


def ov_records(alias: str, args: list[str], path: str, cancel: Cancel) -> list[dict[str, Any]]:
    result = run_ov(["-i", alias, *args, "--json"], timeout=OV_TIMEOUT_SECONDS, cancel=cancel)
    return records(json.loads(_checked(result, alias)), path)
