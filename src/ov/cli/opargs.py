from __future__ import annotations

import argparse
from typing import Any

import httpx

from ov.cli.context import Context
from ov.cli.output import console, emit, emit_payload, note, rows_from
from ov.core.errors import OvError
from ov.onevizion.invoke import RequestPlan, build_plan, dest_name, flag_name
from ov.onevizion.service import payload_of
from ov.onevizion.spec import Operation, Param


def add_invocation_flags(parser: argparse.ArgumentParser, with_path: bool = True) -> None:
    if with_path:
        parser.add_argument("-p", "--param", action="append", metavar="NAME=VALUE", help="path parameter")
    parser.add_argument("-q", "--query", action="append", metavar="NAME=VALUE", help="query parameter")
    parser.add_argument("-H", "--header", action="append", metavar="NAME:VALUE", help="request header")
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
        help="build the body one field at a time; NAME:=VALUE parses VALUE as JSON, and a dotted NAME nests",
    )
    parser.add_argument("--file", action="append", metavar="FIELD=@path", help="upload a file as multipart")
    parser.add_argument("--accept", help="override the Accept header")
    parser.add_argument("--out", metavar="PATH", help="write the response body to a file")
    parser.add_argument("--raw", action="store_true", help="print the response body unformatted")
    parser.add_argument("--table", action="store_true", help="render a list response as a table")
    parser.add_argument("--dry-run", action="store_true", help="print the request that would be sent")


def add_param_flags(parser: argparse.ArgumentParser, operation: Operation) -> None:
    for param in operation.path_params:
        parser.add_argument(
            dest_name(param),
            metavar=param.name.upper(),
            help=_describe(param) or "path parameter",
        )

    for param in operation.params:
        slug = flag_name(param)
        if param.location != "path" and slug is not None:
            parser.add_argument(f"--{slug}", **_flag_options(param))


def _flag_options(param: Param) -> dict[str, Any]:
    options: dict[str, Any] = {"dest": dest_name(param), "help": _describe(param)}
    if param.type.startswith("array"):
        options["action"] = "append"

    if param.enum:
        options["choices"] = param.enum
    else:
        options["metavar"] = param.type.upper().split("[")[0]
    return options


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
        query=args.query,
        path_values=getattr(args, "param", None),
        headers=args.header,
        fields=args.field,
        data=args.data,
        files=args.file,
        accept=args.accept,
    )


def run_operation(ctx: Context, operation: Operation) -> int:
    plan = plan_for(ctx.args, operation)
    if ctx.args.dry_run:
        emit(ctx, {"operation": operation.ref, **plan.to_dict()})
        return 0

    destination = ctx.out_path()
    if destination is None:
        return emit_response(ctx, ctx.service.run(plan))

    saved = ctx.service.download(plan, destination)

    emit(
        ctx,
        {"operation": operation.ref, "path": str(saved), "bytes": saved.stat().st_size},
        text=f"[green]Saved[/green] {saved}",
    )

    return 0


def emit_response(ctx: Context, response: httpx.Response) -> int:
    if ctx.args.raw:
        print(response.text)
        return 0

    payload = payload_of(response)
    if payload is None:
        note(ctx, f"[green]{response.status_code}[/green] [dim]no content[/dim]")
        if ctx.as_json:
            print("null")
        return 0

    if ctx.args.table and not ctx.as_json:
        table = rows_from(payload)
        if table is None:
            raise OvError("That response is not a flat list, so --table has nothing to render.")
        console(ctx).print(table)
        return 0

    emit_payload(ctx, payload)
    return 0
