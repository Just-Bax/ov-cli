from __future__ import annotations

import argparse
from typing import Any

from ..errors import OvError
from ..invoke import RequestPlan, build_plan, dest_name, flag_name
from ..spec import Operation, Param
from .context import Context
from .output import emit, emit_payload, note, rows_from


def add_invocation_flags(parser: argparse.ArgumentParser, with_path: bool = True) -> None:
    """The escape hatches every generated command shares.

    They stay available even where a parameter also has its own flag, because a
    parameter named like one of ours (--json, --out) cannot get one.
    """
    if with_path:
        parser.add_argument(
            "-p", "--param", action="append", metavar="NAME=VALUE", help="path parameter"
        )
    parser.add_argument(
        "-q", "--query", action="append", metavar="NAME=VALUE", help="query parameter"
    )
    parser.add_argument(
        "-H", "--header", action="append", metavar="NAME:VALUE", help="request header"
    )
    parser.add_argument(
        "-d",
        "--data",
        metavar="JSON",
        help="request body as JSON, @file.json, or - to read stdin",
    )
    parser.add_argument(
        "-f",
        "--field",
        action="append",
        metavar="NAME=VALUE",
        help="build the body one field at a time; NAME:=VALUE parses VALUE as JSON, "
        "and a dotted NAME nests",
    )
    parser.add_argument(
        "--file", action="append", metavar="FIELD=@path", help="upload a file as multipart"
    )
    parser.add_argument("--accept", help="override the Accept header")
    parser.add_argument("--out", metavar="PATH", help="write the response body to a file")
    parser.add_argument("--raw", action="store_true", help="print the response body unformatted")
    parser.add_argument("--table", action="store_true", help="render a list response as a table")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the request that would be sent"
    )


def add_param_flags(parser: argparse.ArgumentParser, operation: Operation) -> None:
    """Give the operation's own parameters real flags, so --help documents them."""
    for param in operation.path_params:
        parser.add_argument(
            dest_name(param),
            metavar=param.name.upper(),
            help=_describe(param) or "path parameter",
        )

    for param in operation.params:
        if param.location == "path":
            continue
        slug = flag_name(param)
        if slug is None:
            continue
        kwargs: dict[str, Any] = {
            "dest": dest_name(param),
            "help": _describe(param),
            "metavar": param.type.upper().split("[")[0],
        }
        if param.type.startswith("array"):
            kwargs["action"] = "append"
        if param.enum:
            kwargs["choices"] = param.enum
            kwargs.pop("metavar")
        parser.add_argument(f"--{slug}", **kwargs)


def _describe(param: Param) -> str:
    parts = [param.description.strip()] if param.description else []
    if param.required:
        parts.append("(required)")
    if param.default is not None:
        parts.append(f"[default {param.default}]")
    return " ".join(parts)


def plan_for(args: argparse.Namespace, operation: Operation) -> RequestPlan:
    return build_plan(
        operation,
        vars(args),
        query=getattr(args, "query", None),
        path_values=getattr(args, "param", None),
        headers=getattr(args, "header", None),
        fields=getattr(args, "field", None),
        data=getattr(args, "data", None),
        files=getattr(args, "file", None),
        accept=getattr(args, "accept", None),
    )


def run_operation(ctx: Context, operation: Operation) -> int:
    plan = plan_for(ctx.args, operation)

    if getattr(ctx.args, "dry_run", False):
        emit(ctx, {"operation": operation.ref, **plan.to_dict()})
        return 0

    destination = ctx.out_path()
    if destination is not None:
        saved = ctx.service.download(plan, destination)
        emit(
            ctx,
            {"operation": operation.ref, "path": str(saved), "bytes": saved.stat().st_size},
            text=f"[green]Saved[/green] {saved}",
        )
        return 0

    response = ctx.service.run(plan)
    return emit_response(ctx, response)


def emit_response(ctx: Context, response: Any) -> int:
    if getattr(ctx.args, "raw", False):
        print(response.text)
        return 0

    from ..service import payload_of

    payload = payload_of(response)
    if payload is None:
        note(ctx, f"[green]{response.status_code}[/green] [dim]no content[/dim]")
        if ctx.as_json:
            print("null")
        return 0

    if getattr(ctx.args, "table", False) and not ctx.as_json:
        table = rows_from(payload)
        if table is not None:
            from .output import console

            console(ctx).print(table)
            return 0
        raise OvError("That response is not a flat list, so --table has nothing to render.")

    emit_payload(ctx, payload)
    return 0
