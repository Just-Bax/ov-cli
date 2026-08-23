from __future__ import annotations

import argparse
import json

from ..context import Context
from ..opargs import add_invocation_flags, run_operation
from ..output import build_table, emit, emit_payload


def register(subparsers: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    group = subparsers.add_parser(
        "api",
        parents=[common],
        help="browse and call every operation in the instance's OpenAPI schema",
    )
    actions = group.add_subparsers(dest="action")

    tags = actions.add_parser("tags", parents=[common], help="list operation groups")
    tags.set_defaults(func=cmd_tags)

    listing = actions.add_parser("list", parents=[common], help="list operations")
    listing.add_argument("grep", nargs="?", help="filter by tag, name, path or summary")
    listing.add_argument("--tag", help="only this tag")
    listing.add_argument("--method", help="only this HTTP method")
    listing.add_argument("--deprecated", action="store_true", help="only deprecated operations")
    listing.set_defaults(func=cmd_list)

    show = actions.add_parser("show", parents=[common], help="describe one operation")
    show.add_argument("operation", help="tag:name, a bare name, or 'GET /v3/users'")
    show.set_defaults(func=cmd_show)

    schema = actions.add_parser(
        "schema", parents=[common], help="print an operation's request body schema"
    )
    schema.add_argument("operation", help="tag:name, a bare name, or 'GET /v3/users'")
    schema.set_defaults(func=cmd_schema)

    call = actions.add_parser(
        "call",
        parents=[common],
        help="call any operation by reference",
        description="Parameters go through -p (path), -q (query) and -H (header). "
        "The generated per-tag commands give the same operations named flags instead.",
    )
    call.add_argument("operation", help="tag:name, a bare name, or 'GET /v3/users'")
    add_invocation_flags(call)
    call.set_defaults(func=cmd_call)

    group.set_defaults(func=cmd_tags)


def cmd_tags(ctx: Context) -> int:
    spec = ctx.service.spec(refresh=ctx.refresh)
    counts = [{"tag": tag, "operations": len(spec.by_tag(tag))} for tag in spec.tags]

    def table():
        return build_table(
            f"{spec.title} {spec.version} ({len(spec.operations)} operations)",
            [{"header": "Tag", "style": "cyan"}, {"header": "Ops", "justify": "right"}],
            [[row["tag"], str(row["operations"])] for row in counts],
        )

    emit(ctx, counts, table, empty="No operations in the schema.")
    return 0


def cmd_list(ctx: Context) -> int:
    spec = ctx.service.spec(refresh=ctx.refresh)
    operations = spec.search(ctx.args.grep) if ctx.args.grep else list(spec.operations)
    if ctx.args.tag:
        operations = [o for o in operations if o.tag == ctx.args.tag]
    if ctx.args.method:
        wanted = ctx.args.method.upper()
        operations = [o for o in operations if o.method == wanted]
    if ctx.args.deprecated:
        operations = [o for o in operations if o.deprecated]

    data = [o.to_dict() for o in operations]

    def table():
        return build_table(
            None,
            [
                {"header": "Ref", "style": "cyan", "overflow": "fold"},
                {"header": "Method"},
                {"header": "Path", "overflow": "fold"},
                {"header": "Summary", "overflow": "fold"},
            ],
            [
                [
                    o.ref,
                    o.method,
                    o.path,
                    ("[dim](deprecated)[/dim] " if o.deprecated else "") + o.summary,
                ]
                for o in operations
            ],
        )

    emit(ctx, data, table, empty="Nothing matched.")
    return 0


def cmd_show(ctx: Context) -> int:
    operation = ctx.service.operation(ctx.args.operation, refresh=ctx.refresh)
    data = operation.to_dict(verbose=True)
    data["usage"] = f"ov {operation.tag} {operation.name}"

    def table():
        rows = [
            ["ref", operation.ref],
            ["call", f"{operation.method} {operation.path}"],
            ["usage", data["usage"]],
        ]
        if operation.summary:
            rows.append(["summary", operation.summary])
        if operation.description:
            rows.append(["description", operation.description])
        if operation.deprecated:
            rows.append(["deprecated", "yes"])
        for param in operation.params:
            label = f"{param.location} {param.name}"
            detail = f"{param.type}{' required' if param.required else ''}"
            if param.enum:
                detail += f" one of {', '.join(param.enum)}"
            if param.description:
                detail += f" - {param.description}"
            rows.append([label, detail])
        if operation.body:
            rows.append(
                [
                    "body",
                    f"{operation.body.content_type}"
                    f"{' required' if operation.body.required else ''}"
                    " (ov api schema shows its shape)",
                ]
            )
        return build_table(
            None,
            [{"header": "Field", "style": "cyan"}, {"header": "Value", "overflow": "fold"}],
            rows,
        )

    emit(ctx, data, table)
    return 0


def cmd_schema(ctx: Context) -> int:
    operation = ctx.service.operation(ctx.args.operation, refresh=ctx.refresh)
    if not operation.body:
        emit(
            ctx,
            {"ref": operation.ref, "body": None},
            text=f"{operation.ref} takes no request body.",
        )
        return 0

    emit_payload(ctx, json.loads(json.dumps(operation.body.to_dict(), default=str)))
    return 0


def cmd_call(ctx: Context) -> int:
    operation = ctx.service.operation(ctx.args.operation, refresh=ctx.refresh)
    return run_operation(ctx, operation)
