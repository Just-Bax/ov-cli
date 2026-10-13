from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ov.agent import workspace
from ov.agent.engine.files import within
from ov.agent.instances import components, graph
from ov.agent.instances.ovproc import OvResult, find_instance, host_of, run_ov, url_for
from ov.agent.tools.base import (
    LABEL_CHARS,
    SECRET_JSON,
    SECRET_MASK,
    Tool,
    ToolContext,
    ToolError,
    approved,
    clip,
    int_param,
    string_param,
    strings_param,
)
from ov.core.errors import EXIT_READ_ONLY

OV_TIMEOUT_SECONDS = 180
MAX_SQL_TIMEOUT_SECONDS = 600
DEFAULT_SQL_ROWS = 100
MAX_SQL_ROWS = 1000
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 500
MAP_MAX_MATCHES = 5
MAP_LISTED_MATCHES = 20
MAX_EXPORT_IDS = 20
EXPORT_INLINE_CHARS = 200
LABEL_ARGS = 4
SIGN_IN_ATTEMPTS = 2
APPLIED = "Applied.\n"
IMPORT_FILE_PREFIX = "import-"

BLOCKED_COMMANDS = {"login", "logout", "use", "config", "setup", "spec", "tenants", "agent", "ui"}
CONFINED_FLAGS = ("--out", "--file", "--data")

EDIT_FORMS = (
    (re.compile(r"rule", re.IGNORECASE), "/admin/rules/Form.do?id="),
    (re.compile(r"report", re.IGNORECASE), "/admin/reports/Form.do?id="),
    (re.compile(r"automation", re.IGNORECASE), "/admin/automation/Form.do?id="),
    (re.compile(r"trackor|record", re.IGNORECASE), "/form/ConfigAppForm.do?id="),
)

_SQL_ROUTE = re.compile(r"^/?(api/)?v\d+/sql/", re.IGNORECASE)
_SELECT = re.compile(r"^(select|with)\b", re.IGNORECASE)
_PLSQL_IN_WITH = re.compile(r"\bwith\s+(function|procedure)\b", re.IGNORECASE)
_SECRET_SQL = re.compile(r"\bselect\s+\*\s+from\s+(module|users?|auth_token\w*)\b", re.IGNORECASE)
_SECRET_NAME = re.compile(r"pass(word|wd)?|secret|token|api_?key|private_?key|credential", re.IGNORECASE)
_SECRET_KEY = re.compile(r"^[\w.\-]{0,60}$")


def entity_link(entity_type: str, entity_id: str | None, instance: str | None) -> str | None:
    if not entity_id or not instance or not entity_id.strip().isdigit():
        return None
    form = next((path for pattern, path in EDIT_FORMS if pattern.search(entity_type)), None)
    return f"{url_for(instance)}{form}{entity_id.strip()}" if form else None


def _output(result: OvResult) -> str:
    stderr = result.stderr.strip()
    body = "\n".join(p for p in (result.stdout.strip(), stderr and f"[stderr] {stderr}") if p)
    if result.code != 0:
        raise ToolError(body or f"ov exited with code {result.code}")
    return body or "(empty response)"


def _target(instance: str | None, ctx: ToolContext) -> str:
    target = (instance or ctx.instance).strip()
    if not target:
        raise ToolError("No instance given. Pass instance, or ask the user which one.")
    return target


def _alias_for(target: str, ctx: ToolContext) -> tuple[str, str, str]:
    found = find_instance(target)
    if found is not None:
        return found["alias"], found["host"], found["tenant"] or ""
    if not ctx.require_login(host_of(target)):
        raise ToolError(f"Not signed in to {target} and the user skipped sign-in.")

    found = find_instance(target)
    if found is None:
        raise ToolError(f"Still no signed-in instance for {target}.")
    return found["alias"], found["host"], found["tenant"] or ""


def _quoted(args: list[str]) -> str:
    return " ".join(json.dumps(a) if re.search(r"[\s\"']", a) else a for a in args)


def _confine(path: str, ctx: ToolContext) -> str:
    return str(within(ctx.work_dir, Path(path).name))


def _confine_value(flag: str, value: str, ctx: ToolContext) -> str:
    if flag == "--out":
        return _confine(value, ctx)
    if flag == "--file":
        field, _, path = value.partition("=")
        return f"{field}=@{_confine(path.strip().lstrip('@'), ctx)}"
    if value.startswith("@"):
        return "@" + _confine(value[1:], ctx)
    return value


def _confine_files(args: list[str], ctx: ToolContext) -> list[str]:
    out: list[str] = []
    expect = ""
    for arg in args:
        if expect:
            out.append(_confine_value(expect, arg, ctx))
            expect = ""
            continue

        flag, sep, value = arg.partition("=")
        if flag in (*CONFINED_FLAGS, "-d") and not sep:
            expect = "--data" if flag == "-d" else flag
            out.append(arg)
        elif sep and flag in CONFINED_FLAGS:
            out.extend([flag, _confine_value(flag, value, ctx)])
        elif arg.startswith("-d") and len(arg) > 2 and not arg.startswith("--"):
            out.extend(["-d", _confine_value("--data", arg[2:].removeprefix("="), ctx)])
        else:
            out.append(arg)
    return out


def _check_ov_args(args: list[str], allow_sql: bool) -> None:
    if not args:
        raise ToolError("No ov arguments given.")
    if args[0].startswith("-"):
        raise ToolError('Start with the command, e.g. ["request", "GET", "/v3/..."].')
    if args[0] in BLOCKED_COMMANDS:
        raise ToolError(f'"{args[0]}" is not allowed from the agent.')
    if any(a.startswith("--instance") or (a.startswith("-i") and a[:2] != "--") for a in args):
        raise ToolError("Pass the instance in the instance parameter, not as -i.")
    if not allow_sql and (args[0] == "sql" or any(_SQL_ROUTE.search(a) for a in args)):
        raise ToolError("Run SQL with the ov_sql tool, not through ov.")


def run_ov_tool(
    args: list[str],
    instance: str | None,
    ctx: ToolContext,
    allow_sql: bool = False,
    *,
    raw: bool = False,
    timeout: int = OV_TIMEOUT_SECONDS,
) -> str:
    cleaned = [str(a) for a in args]
    if cleaned[:1] == ["ov"]:
        cleaned.pop(0)
    _check_ov_args(cleaned, allow_sql)
    cleaned = _confine_files(cleaned, ctx)
    target = _target(instance, ctx)

    for attempt in range(SIGN_IN_ATTEMPTS):
        alias, host, tenant = _alias_for(target, ctx)
        result = run_ov(
            ["-i", alias, *cleaned],
            timeout=timeout,
            cancel=ctx.cancel,
            cwd=ctx.work_dir,
        )
        if result.is_auth and attempt < SIGN_IN_ATTEMPTS - 1:
            if not ctx.require_login(host, tenant):
                raise ToolError(f"Session for {target} expired and the user skipped sign-in.")
            continue
        if result.timed_out:
            raise ToolError(f"ov timed out after {timeout}s")
        output = APPLIED + _write(alias, host, cleaned, ctx) if result.code == EXIT_READ_ONLY else _output(result)
        return output if raw else clip(output, ctx, "ov output")
    raise ToolError(f"Still not signed in to {target}.")


def _write(alias: str, host: str, args: list[str], ctx: ToolContext) -> str:
    blocked = ToolError(
        "Blocked: this would change data and write access is OFF for this run. Do not "
        "retry. Tell the user in chat what you would change and that they can turn on "
        '"Allow changes" below the chat if they want you to apply it.'
    )
    if not ctx.can_write():
        raise blocked

    command = f"ov -i {host} {_quoted(args)}"
    if not approved(ctx, f"Apply this change on {host}?", command):
        raise ToolError("The user rejected this change. Do not retry it.")
    if not ctx.can_write():
        raise blocked

    result = run_ov(
        ["-i", alias, *args],
        timeout=OV_TIMEOUT_SECONDS,
        read_only=False,
        cancel=ctx.cancel,
        cwd=ctx.work_dir,
    )
    if result.timed_out:
        raise ToolError(f"ov timed out after {OV_TIMEOUT_SECONDS}s")
    return _output(result)


def _sql_cell(value: Any) -> str:
    if value is None:
        return "NULL"
    return str(value).replace("\t", " ").replace("\r\n", "\\n").replace("\n", "\\n")


def _masked(columns: list[str], cells: list[Any]) -> list[Any]:
    secret_row = any(isinstance(c, str) and _SECRET_KEY.match(c) and _SECRET_NAME.search(c) for c in cells)
    out = []
    for name, cell in zip(columns, cells, strict=True):
        if cell is None or isinstance(cell, (int, float)):
            out.append(cell)
        elif _SECRET_NAME.search(name) or (
            secret_row and not (_SECRET_KEY.match(str(cell)) and _SECRET_NAME.search(str(cell)))
        ):
            out.append(SECRET_MASK)
        else:
            out.append(SECRET_JSON.sub(rf'\1"{SECRET_MASK}"', str(cell)))
    return out


def _format_sql(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise ToolError(f"Unexpected SQL response: {raw}") from None
    if not isinstance(parsed, dict):
        raise ToolError(f"Unexpected SQL response: {raw}")
    if parsed["status"] != "SUCCESS":
        raise ToolError(f"SQL failed: {parsed.get('error_message') or raw}")

    rows = parsed["rows"]
    columns = parsed["columns"]
    lines = ["\t".join(columns)]
    lines += ["\t".join(_sql_cell(c) for c in _masked(columns, row["cells"])) for row in rows]
    total = parsed.get("total_rows")
    more = f", {total} total" if total and total > len(rows) else ""
    return f"{len(rows)} rows{more} (tab separated)\n" + "\n".join(lines)


def _ov_sql(args: dict[str, Any], ctx: ToolContext) -> str:
    query = re.sub(r";\s*$", "", str(args["query"]).strip())
    if not _SELECT.match(query) or _PLSQL_IN_WITH.search(query):
        raise ToolError("Only SELECT / WITH queries are allowed.")
    if _SECRET_SQL.search(query):
        raise ToolError(
            "Refused: select * from this table can include credentials. Name the columns you need; "
            "secret-looking values are masked in results."
        )

    rows = min(max(int(args.get("limit") or DEFAULT_SQL_ROWS), 1), MAX_SQL_ROWS)
    timeout = min(max(int(args.get("timeout") or OV_TIMEOUT_SECONDS), 1), MAX_SQL_TIMEOUT_SECONDS)
    started = time.monotonic()
    try:
        raw = run_ov_tool(
            [
                *graph.SQL_REQUEST,
                "-q",
                f"rows_count={rows}",
                "-d",
                query,
                "--json",
            ],
            args.get("instance"),
            ctx,
            allow_sql=True,
            raw=True,
            timeout=timeout,
        )
    except ToolError as exc:
        if "timed out" not in str(exc):
            raise
        raise ToolError(
            f"The query did not finish in {timeout}s and may still be running on the database. Do not retry "
            "it unchanged: narrow it with selective key or date filters, or sample with fetch first."
        ) from None
    took = time.monotonic() - started
    return clip(f"{_format_sql(raw)}\n[took {took:.1f}s including the ov call]", ctx, "result")


def _export_ids(args: dict[str, Any]) -> list[int]:
    ids = [int(str(i).strip()) for i in args["ids"]]
    if not ids or len(ids) > MAX_EXPORT_IDS:
        raise ToolError(f"Give 1 to {MAX_EXPORT_IDS} component ids.")
    return ids


def _export_item(item: Any, component_type: str, ids: set[str], ctx: ToolContext) -> str:
    values = components.fields(item)
    ident = next((v for k, v in values.items() if k.endswith("_ID") and v in ids), "item")
    lines = []
    for tag, value in values.items():
        if "\n" in value or len(value) > EXPORT_INLINE_CHARS:
            name = f"{component_type.lower()}-{ident}-{tag.lower()}.txt"
            (ctx.work_dir / name).write_text(value, encoding="utf-8")
            lines.append(f"  {tag}: {value.count(chr(10)) + 1} lines in {name}")
        elif value.strip():
            lines.append(f"  {tag}: {value}")

    filled = [f"{tag} ({count})" for tag, count in components.lists(item).items()]
    if filled:
        lines.append(f"  Lists: {', '.join(filled)}")
    return f"{component_type} {ident}\n" + "\n".join(lines)


def _ov_export(args: dict[str, Any], ctx: ToolContext) -> str:
    component_type = str(args["component_type"]).upper()
    try:
        ids = _export_ids(args)
        request = components.request_args(component_type, ids)
    except components.ExportError as exc:
        raise ToolError(str(exc)) from None

    name = f"export-{int(time.time() * 1000)}.xml"
    run_ov_tool([*request, "--out", name], args.get("instance"), ctx)
    found = components.items((ctx.work_dir / name).read_text(encoding="utf-8"))
    if not found:
        raise ToolError(f"The export returned no {component_type} with those ids.")

    body = "\n\n".join(_export_item(item, component_type, set(map(str, ids)), ctx) for item in found)
    return (
        f"Exported {len(found)} {component_type} (full XML in {name}).\n\n{body}\n\n"
        "Read the files with run_read, using start and end for line ranges."
    )


def _import_file(name: str, ctx: ToolContext) -> str:
    in_run = within(ctx.work_dir, Path(name).name)
    if in_run.is_file():
        return in_run.name
    if not workspace.configured():
        raise ToolError(f"No file {name} in the run folder, and no workspace is set.")

    source = workspace.resolve(name)
    if not source.is_file():
        raise ToolError(f"No file {name} in the run folder or the workspace.")
    copy = ctx.work_dir / f"{IMPORT_FILE_PREFIX}{int(time.time() * 1000)}{source.suffix}"
    shutil.copyfile(source, copy)
    return copy.name


def _ov_import(args: dict[str, Any], ctx: ToolContext) -> str:
    dry_run = args.get("dry_run", True) is not False
    try:
        request = components.import_args(_import_file(str(args["file"]), ctx), args.get("components") or [], dry_run)
        output = run_ov_tool([*request, "--raw"], args.get("instance"), ctx, raw=True)
        summary = components.import_summary(output.removeprefix(APPLIED))
    except components.ExportError as exc:
        raise ToolError(str(exc)) from None

    if dry_run:
        return f"Dry run, nothing changed:\n{summary}\n\nCall again with dry_run false to import."
    return f"Imported:\n{summary}"


def _ov_search(args: dict[str, Any], ctx: ToolContext) -> str:
    trackor_type = quote(str(args["trackor_type"]), safe="")
    limit = min(int(args.get("limit") or DEFAULT_SEARCH_LIMIT), MAX_SEARCH_LIMIT)
    return run_ov_tool(
        [
            "request",
            "POST",
            f"/v3/trackor_types/{trackor_type}/trackors/search",
            "-q",
            f"fields={','.join(args['fields'])}",
            "-q",
            "page=1",
            "-q",
            f"per_page={limit}",
            "-H",
            "Content-Type:text/plain",
            "-d",
            str(args["condition"]),
            "--json",
        ],
        args.get("instance"),
        ctx,
    )


def _ov_map(args: dict[str, Any], ctx: ToolContext) -> str:
    target = _target(args.get("instance"), ctx)
    found = find_instance(target)
    if found is None:
        raise ToolError(f"Not signed in to {target}.")

    data = graph.load(found["alias"]) or graph.build(found["alias"], cancel=ctx.cancel)
    matches = graph.find(data, str(args["object"]))
    if not matches:
        return f"Nothing named like {args['object']!r} on the {found['alias']} map."
    if len(matches) > MAP_MAX_MATCHES:
        listed = "\n".join(f"- {m['type']} {m['name']} ({m['ref']})" for m in matches[:MAP_LISTED_MATCHES])
        return f"{len(matches)} matches; pass the exact name or id:\n{listed}"

    built = time.strftime("%Y-%m-%d %H:%M", time.localtime(data["builtAt"] / 1000))
    body = "\n\n".join(graph.describe(data, m) for m in matches)
    return clip(f"Map of {found['alias']} built {built}.\n\n{body}", ctx, "map")


def _ov_label(a: dict[str, Any]) -> str:
    at = f" @ {a['instance']}" if a.get("instance") else ""
    return f"ov {' '.join(str(x) for x in (a.get('args') or [])[:LABEL_ARGS])}{at}"


INSTANCE = string_param("Instance alias or host. Defaults to the run's instance, if one is set.")

TOOLS = [
    Tool(
        "ov_case",
        "Read a support case from trackor.onevizion.com: every field, the full chat, and all "
        "attachments (saved to the run folder; open each with run_read). Also sets the run's "
        "instance to the case's affected instance (C_WEBSITE).",
        {"case": string_param("Case number (e.g. 193915) or a trackor.onevizion.com case link")},
        ["case"],
        lambda a: f"Read case {a.get('case')} from trackor",
        lambda a, ctx: ctx.load_case(str(a["case"])),
    ),
    Tool(
        "ov",
        "Run the ov CLI against a OneVizion instance: any API call, schema discovery (api list, "
        "api show), component export, chats, files. Reads always work. Calls that change data "
        "are blocked unless the user allowed changes for this run, and then each one waits for "
        "the user to approve it.",
        {
            "instance": INSTANCE,
            "args": strings_param(
                'Arguments after "ov -i <alias>", e.g. ["request","GET","/v3/trackors/123","-q","fields=A,B"]'
            ),
        },
        ["args"],
        _ov_label,
        lambda a, ctx: run_ov_tool(list(a["args"]), a.get("instance"), ctx),
    ),
    Tool(
        "ov_map",
        "Look an object up on the Map: what a trackor type, field, rule, automation, "
        "import, report, notification, workflow, module or DB package is linked to (relations, "
        "fields, triggers, packages it calls, and objects its code references by quoted name, "
        "config id or id.* object reference). Fast, no SQL needed. Builds the map on first use "
        "(about a minute). Use it before changing anything to see what depends on it.",
        {
            "instance": INSTANCE,
            "object": string_param("Name or id of the object, e.g. C_STATUS, a rule name, or 100121663"),
        },
        ["object"],
        lambda a: f"map {a.get('object')}{' @ ' + a['instance'] if a.get('instance') else ''}",
        _ov_map,
    ),
    Tool(
        "ov_sql",
        "Run a read-only SELECT (or WITH) on an instance database through the platform's Test "
        "SQL endpoint. Max 1000 rows. Secret-looking values are masked in the result.",
        {
            "instance": INSTANCE,
            "query": string_param("A single SELECT statement, no trailing semicolon"),
            "limit": int_param("Row limit, default 100, max 1000"),
            "timeout": int_param(f"Seconds, default {OV_TIMEOUT_SECONDS}, max {MAX_SQL_TIMEOUT_SECONDS}"),
        },
        ["query"],
        lambda a: (
            f"SQL{' @ ' + a['instance'] if a.get('instance') else ''}: "
            + re.sub(r"\s+", " ", str(a.get("query", "")))[:LABEL_CHARS]
        ),
        _ov_sql,
    ),
    Tool(
        "ov_export",
        "Export components from an instance with the platform's component export and save their "
        "code to files in the run folder: a DB package's full spec and body, a rule's SQL, an import's or "
        "report's SQL and settings. One call, however long the code; prefer it to paging CLOBs "
        "through ov_sql.",
        {
            "instance": INSTANCE,
            "component_type": {"type": "string", "enum": list(components.TYPES)},
            "ids": {"type": "array", "items": {"type": "integer"}, "description": "Component ids, up to 20"},
        },
        ["component_type", "ids"],
        lambda a: f"export {a.get('component_type')} {', '.join(map(str, a.get('ids') or []))}"[:LABEL_CHARS],
        _ov_export,
    ),
    Tool(
        "ov_import",
        "Import components into an instance with the platform's component import, from a component "
        "export XML: an ov_export file in the run folder, or a file in the workspace. Always run it "
        "with dry_run true first and show the user what it would do; a real import needs Allow changes "
        "and the user's approval. Leave components out to import everything in the file.",
        {
            "instance": INSTANCE,
            "file": string_param("Export XML: a file name in the run folder, or a path inside the workspace"),
            "components": {
                "type": "array",
                "description": "Which components to import and how; leave out to import all",
                "items": {
                    "type": "object",
                    "properties": {
                        "component_type": {"type": "string", "enum": list(components.IMPORT_TYPES)},
                        "mode": {"type": "string", "enum": list(components.IMPORT_MODES)},
                        "ids": {"type": "array", "items": {"type": "integer"}, "description": "Only these ids"},
                    },
                    "required": ["component_type"],
                    "additionalProperties": False,
                },
            },
            "dry_run": {"type": "boolean", "description": "Check without changing anything. Default true"},
        },
        ["file"],
        lambda a: f"import {a.get('file')}{' (dry run)' if a.get('dry_run', True) is not False else ''}"[:LABEL_CHARS],
        _ov_import,
    ),
    Tool(
        "ov_search",
        "Search trackors of a type with a condition (equal, not_equal, greater, less, within, "
        "is_null, is_not_null, and/or, parentheses). String and date values in double quotes.",
        {
            "instance": INSTANCE,
            "trackor_type": string_param("Trackor type name"),
            "fields": strings_param("Field names to return"),
            "condition": string_param('e.g. equal(TRACKOR_KEY, "P-100") and greater(F_DATE, "2026-01-01")'),
            "limit": int_param("Max rows, default 50"),
        },
        ["trackor_type", "fields", "condition"],
        lambda a: f"search {a.get('trackor_type')}: {str(a.get('condition', ''))[:LABEL_CHARS]}",
        _ov_search,
    ),
]
