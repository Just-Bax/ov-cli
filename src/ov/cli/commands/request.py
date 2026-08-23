from __future__ import annotations

import argparse

from ...spec import METHODS, Operation
from ..context import Context
from ..opargs import add_invocation_flags, run_operation


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    group = subparsers.add_parser(
        "request",
        parents=[common],
        help="call any API path directly, without consulting the schema",
        description="The escape hatch for endpoints the OpenAPI schema does not "
        "describe, such as the internal API, and for a server whose schema is "
        "unreadable. Paths are relative to /api.",
    )
    group.add_argument("method", choices=[m.upper() for m in METHODS] + list(METHODS))
    group.add_argument("path", help="e.g. /v3/schema/trackor_types")
    add_invocation_flags(group, with_path=False)
    group.set_defaults(func=cmd_request)


def cmd_request(ctx: Context) -> int:
    operation = Operation(
        name="request",
        tag="raw",
        method=ctx.args.method.upper(),
        path=ctx.args.path,
        summary="ad-hoc request",
    )
    return run_operation(ctx, operation)
