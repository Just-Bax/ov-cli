from __future__ import annotations

import time
from typing import Any

from ov.cli.context import Context
from ov.cli.output import console
from ov.core.errors import EXIT_ERROR, NotFound, OvError
from ov.onevizion.service import payload_of
from ov.onevizion.spec import Operation

POLL_SECONDS = 3
RUN_SUFFIX = "/run"
STATUS_SUFFIX = "/runs/{process_id}"
PROCESS_ID = "process_id"
STATUS = "status"
UNFINISHED = frozenset(
    {
        "PENDING",
        "IN_QUEUE",
        "RUNNING",
        "RUNNING_IMPORTING_DATA",
        "RUNNING_PARSING_CSV",
        "RUNNING_CREATING_ENTITIES",
        "RUNNING_GENERATING_DATA_TYPE_SQL",
        "RUNNING_RULES_IMP_START",
        "RUNNING_RULES_IMP_COMPLETE",
        "RECOVERING",
        "AWAITING_PDF",
        "INTERRUPTING",
    }
)
FAILED = frozenset({"EXECUTED_WITH_ERRORS", "INTERRUPTED", "NUM_CELLS_LIMIT_EXCEEDED", "CLEANUP_HANGED_PROCESS"})


def status_operation(ctx: Context, operation: Operation) -> Operation:
    if not operation.path.endswith(RUN_SUFFIX):
        raise OvError(f"--wait needs an operation that starts a run; {operation.method} {operation.path} does not.")

    collection = operation.path.removesuffix(RUN_SUFFIX)
    if collection.endswith("}"):
        collection = collection.rsplit("/", 1)[0]

    status_path = collection + STATUS_SUFFIX
    try:
        return ctx.service.operation(f"GET {status_path}")
    except NotFound:
        raise OvError(f"--wait cannot follow {operation.path}: the API has no GET {status_path}.") from None


def wait_for_run(ctx: Context, status_op: Operation, started: Any) -> tuple[dict[str, Any], int]:
    if not isinstance(started, dict) or PROCESS_ID not in started:
        raise OvError(f"The run started, but the response has no {PROCESS_ID} to follow.")

    path = status_op.path.replace("{" + PROCESS_ID + "}", str(started[PROCESS_ID]))
    run = started
    with console(ctx, stderr=True).status(_label(run), spinner="dots") as shown:
        while _status(run) in UNFINISHED:
            time.sleep(POLL_SECONDS)
            run = payload_of(ctx.client.api("GET", path))
            shown.update(_label(run))

    return run, EXIT_ERROR if _status(run) in FAILED else 0


def _status(run: dict[str, Any]) -> str:
    if STATUS not in run:
        raise OvError(f"Run {run.get(PROCESS_ID)} came back without a {STATUS}.")
    return str(run[STATUS])


def _label(run: dict[str, Any]) -> str:
    return f"Run {run[PROCESS_ID]}: {_status(run)}"
