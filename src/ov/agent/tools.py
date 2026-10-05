from __future__ import annotations

import base64
import itertools
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from ..errors import EXIT_READ_ONLY
from . import datadog, graph, pagerduty, skills, sources
from .cancel import Cancel
from .ovproc import OvResult, find_instance, host_of, run_ov
from .workspace import IMAGE_EXTS, image_mime, within

MAX_OUTPUT = 24_000
OV_TIMEOUT_SECONDS = 180
MAX_TIME_SAVED_MINUTES = 8 * 60
DEFAULT_SQL_ROWS = 100
MAX_SQL_ROWS = 1000
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 500
READ_FILE_LINES = 500
BINARY_SNIFF_BYTES = 4096
MAP_MAX_MATCHES = 5
MAP_LISTED_MATCHES = 20
LOG_PATTERN_SCAN = 500
LOG_PATTERN_GROUPS = 15
DEFAULT_LOG_LINES = 30
MAX_MONITORS_SHOWN = 60
MAX_SERIES_SHOWN = 10
DEFAULT_EVENTS = 30
DEFAULT_ERROR_SPANS = 25
DEFAULT_SLOW_ENDPOINTS = 10
DEFAULT_INCIDENTS = 25
ONCALL_LOOKBACK_DAYS = 30
DAY_MS = 86_400_000
LABEL_CHARS = 60
LABEL_ARGS = 4

BLOCKED_COMMANDS = {"login", "logout", "use", "config", "setup", "spec", "tenants", "agent", "ui"}
CONFINED_FLAGS = ("--out", "--file", "--data")

EDIT_FORMS = (
    (re.compile(r"rule", re.IGNORECASE), "/admin/rules/Form.do?id="),
    (re.compile(r"report", re.IGNORECASE), "/admin/reports/Form.do?id="),
    (re.compile(r"automation", re.IGNORECASE), "/admin/automation/Form.do?id="),
    (re.compile(r"trackor|record", re.IGNORECASE), "/form/ConfigAppForm.do?id="),
)

_counter = itertools.count(1)


class ToolError(Exception):
    pass


class ToolContext(Protocol):
    work_dir: Path
    cancel: Cancel
    vision: bool
    instance: str
    opened: set[str]

    def emit(self, event: dict[str, Any]) -> None: ...
    def has_outcome(self) -> bool: ...
    def ask_user(self, question: str, options: list[str], multiple: bool, detail: str | None = None) -> str: ...
    def require_login(self, host: str, tenant: str = "") -> bool: ...
    def attach_image(self, name: str, url: str) -> None: ...
    def finish(self, outcome: dict[str, Any]) -> None: ...
    def can_write(self) -> bool: ...
    def load_case(self, ref: str) -> str: ...


Handler = Callable[[dict[str, Any], ToolContext], str]


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    label: Callable[[dict[str, Any]], str]
    handler: Handler
    silent: bool = False

    @property
    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
                    "required": self.required,
                    "additionalProperties": False,
                },
            },
        }


def _str(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _int(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


def _strings(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def entity_link(entity_type: str, entity_id: str | None, instance: str | None) -> str | None:
    if not entity_id or not instance or not entity_id.strip().isdigit():
        return None
    form = next((path for pattern, path in EDIT_FORMS if pattern.search(entity_type)), None)
    return f"https://{host_of(instance)}{form}{entity_id.strip()}" if form else None


def clip(text: str, ctx: ToolContext, what: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text

    name = f"output-{int(time.time() * 1000)}-{next(_counter)}.txt"
    (ctx.work_dir / name).write_text(text, encoding="utf-8")
    return (
        f"{text[:MAX_OUTPUT]}\n\n[truncated: {len(text)} chars total. Full {what} saved as "
        f'"{name}"; read more with read_file]'
    )


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
    if found is None:
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


_SQL_ROUTE = re.compile(r"^/?(api/)?v\d+/sql/", re.IGNORECASE)


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


def run_ov_tool(args: list[str], instance: str | None, ctx: ToolContext, allow_sql: bool = False) -> str:
    cleaned = [str(a) for a in args]
    if cleaned[:1] == ["ov"]:
        cleaned.pop(0)
    _check_ov_args(cleaned, allow_sql)
    cleaned = _confine_files(cleaned, ctx)
    target = _target(instance, ctx)

    for attempt in range(2):
        alias, host, tenant = _alias_for(target, ctx)
        result = run_ov(
            ["-i", alias, *cleaned],
            timeout=OV_TIMEOUT_SECONDS,
            cancel=ctx.cancel,
            cwd=ctx.work_dir,
        )
        if result.is_auth and attempt == 0:
            if not ctx.require_login(host, tenant):
                raise ToolError(f"Session for {target} expired and the user skipped sign-in.")
            continue
        if result.timed_out:
            raise ToolError(f"ov timed out after {OV_TIMEOUT_SECONDS}s")
        if result.code == EXIT_READ_ONLY:
            return _write(alias, host, cleaned, ctx)
        return clip(_output(result), ctx, "ov output")
    raise ToolError(f"Still not signed in to {target}.")


def _write(alias: str, host: str, args: list[str], ctx: ToolContext) -> str:
    blocked = ToolError(
        "Blocked: this would change data and write access is OFF for this run. Do not "
        "retry. Show the change with propose_change and tell the user they can turn on "
        '"Allow changes" below the chat if they want you to apply it.'
    )
    if not ctx.can_write():
        raise blocked

    command = f"ov -i {host} {_quoted(args)}"
    answer = ctx.ask_user(f"Apply this change on {host}?", ["Approve", "Reject"], False, command)
    if answer != "Approve":
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
    return clip(f"Applied.\n{_output(result)}", ctx, "ov output")


def _sql_cell(value: Any) -> str:
    if value is None:
        return "NULL"
    return str(value).replace("\t", " ").replace("\r\n", "\\n").replace("\n", "\\n")


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
    lines = ["\t".join(parsed["columns"])]
    lines += ["\t".join(_sql_cell(c) for c in row["cells"]) for row in rows]
    total = parsed.get("total_rows")
    more = f", {total} total" if total and total > len(rows) else ""
    return f"{len(rows)} rows{more} (tab separated)\n" + "\n".join(lines)


_SELECT = re.compile(r"^(select|with)\b", re.IGNORECASE)
_PLSQL_IN_WITH = re.compile(r"\bwith\s+(function|procedure)\b", re.IGNORECASE)
_SECRET_SQL = re.compile(
    r"password|passwd|secret|\bselect\s+\*\s+from\s+(module|users?|auth_token\w*)\b", re.IGNORECASE
)


def _ov_sql(args: dict[str, Any], ctx: ToolContext) -> str:
    query = re.sub(r";\s*$", "", str(args["query"]).strip())
    if not _SELECT.match(query) or _PLSQL_IN_WITH.search(query):
        raise ToolError("Only SELECT / WITH queries are allowed.")
    if _SECRET_SQL.search(query):
        raise ToolError("Do not read credential columns. Select the non-secret columns you need.")

    rows = min(max(int(args.get("rows") or DEFAULT_SQL_ROWS), 1), MAX_SQL_ROWS)
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
    )
    return clip(_format_sql(raw), ctx, "result")


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


def attachment_names(ctx: ToolContext) -> list[str]:
    directory = ctx.work_dir / "attachments"
    if not directory.is_dir():
        return []
    names = {p.name for p in directory.iterdir()}
    return sorted(n for n in names if not (n.endswith(".txt") and n[:-4] in names))


def offered_skills() -> list[dict[str, Any]]:
    hidden = {
        name for name, linked in (("datadog", datadog.connected), ("pagerduty", pagerduty.connected)) if not linked()
    }
    return [s for s in skills.enabled_skills() if s["name"] not in hidden]


def _read_skill(args: dict[str, Any], _ctx: ToolContext) -> str:
    name = str(args["name"]).strip()
    found = next((s for s in offered_skills() if s["name"] == name), None)
    if found is None:
        names = ", ".join(s["name"] for s in offered_skills())
        raise ToolError(f"No skill named {name}. Skills: {names}.")

    return f"# {found['title']}\n\n{found['content']}"


def _locate(rel: str, ctx: ToolContext) -> Path:
    path = within(ctx.work_dir, rel)
    if not path.exists() and (ctx.work_dir / "attachments").is_dir():
        path = within(ctx.work_dir / "attachments", Path(rel).name)
    if not path.is_file():
        listed = ", ".join(attachment_names(ctx)) or "none"
        raise ToolError(f"No such file: {rel}. Attachments: {listed}")

    if path.parent.name == "attachments":
        ctx.opened.add(path.name)
    return path


def _read_image(path: Path, ctx: ToolContext) -> str:
    if not ctx.vision:
        return "This model cannot view images. Switch to a vision model to read screenshots."

    data = base64.b64encode(path.read_bytes()).decode("ascii")
    ctx.attach_image(path.name, f"data:{image_mime(path)};base64,{data}")
    return f"Image {path.name} is attached in the next message."


def _read_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = _locate(str(args["path"]), ctx)
    if path.suffix.lower() in IMAGE_EXTS:
        return _read_image(path, ctx)

    expanded = Path(f"{path}.txt")
    if path.suffix.lower() == ".eml" and expanded.exists():
        path = expanded
    raw = path.read_bytes()
    if b"\0" in raw[:BINARY_SNIFF_BYTES]:
        return f"Binary file {path.name} ({len(raw)} bytes); cannot be read as text."

    lines = raw.decode("utf-8", "replace").split("\n")
    first = max(1, int(args.get("start") or 1))
    last = min(len(lines), int(args.get("end") or first + READ_FILE_LINES - 1))
    tail = f"\n... ({len(lines)} lines)" if last < len(lines) else ""
    return clip("\n".join(lines[first - 1 : last]) + tail, ctx, "file")


def _source_search(args: dict[str, Any], ctx: ToolContext) -> str:
    found = sources.search(
        str(args["source"]),
        str(args["pattern"]),
        str(args.get("path") or ""),
        bool(args.get("ignore_case")),
    )
    return clip(found, ctx, "search")


def _source_read(args: dict[str, Any], ctx: ToolContext) -> str:
    end = int(args["end"]) if args.get("end") else None
    text = sources.read(str(args["source"]), str(args["path"]), int(args.get("start") or 1), end)
    return clip(text, ctx, "file")


def _github_clone(args: dict[str, Any], _ctx: ToolContext) -> str:
    cloned = sources.clone_repo(str(args["url"]))
    return f'Use source="{cloned["repo"]}".\nFiles:\n' + "\n".join(cloned["files"])


def _propose_change(args: dict[str, Any], ctx: ToolContext) -> str:
    entity_type = str(args["entity_type"])
    entity_id = str(args["entity_id"]) if args.get("entity_id") else None
    instance = str(args.get("instance") or ctx.instance) or None
    change = {
        "id": f"chg_{int(time.time() * 1000)}_{next(_counter)}",
        "title": str(args["title"]),
        "entityType": entity_type,
        "entityId": entity_id,
        "entityName": str(args["entity_name"]) if args.get("entity_name") else None,
        "instance": instance,
        "link": entity_link(entity_type, entity_id, instance) or args.get("link") or None,
        "language": "sql" if args["language"] == "plsql" else str(args["language"]),
        "before": str(args.get("before") or ""),
        "after": str(args["after"]),
        "what": str(args["what"]),
        "why": str(args["why"]),
        "how": str(args["how"]),
    }

    ctx.emit({"type": "change", "change": {k: v for k, v in change.items() if v is not None}})
    return f"Change card shown ({change['id']})."


def _ask_user(args: dict[str, Any], ctx: ToolContext) -> str:
    options = [str(o) for o in args["options"]]
    return f"User answered: {ctx.ask_user(str(args['question']), options, bool(args.get('multiple')))}"


def _existing(entries: list[Any]) -> list[dict[str, str]]:
    if any(not isinstance(e, dict) or not e.get("key") for e in entries):
        raise ToolError("Every existing entry needs a key.")
    return [{k: str(e[k]) for k in ("key", "title", "covers", "note", "link") if e.get(k)} for e in entries]


def _finish(args: dict[str, Any], ctx: ToolContext) -> str:
    findings = args["findings"]
    if any(not f.get("evidence") for f in findings):
        raise ToolError(
            "Not finished: every finding needs evidence you verified yourself. Check, then call finish again."
        )

    unread = [] if ctx.has_outcome() else [n for n in attachment_names(ctx) if n not in ctx.opened]
    if unread:
        raise ToolError(f"Not finished: open every attachment first. Unread: {', '.join(unread)}")

    minutes = round(float(args["time_saved_minutes"]))
    outcome = {
        "issues": [
            {
                "title": str(f["title"]),
                "verdict": str(f["verdict"]),
                "summary": str(f["summary"]),
                "stillHappening": f.get("still_happening"),
                "evidence": [str(e) for e in f["evidence"]],
            }
            for f in findings
        ],
        "existing": _existing(args.get("existing") or []),
        "unrelated": [str(u) for u in args.get("unrelated") or []],
        "reply": str(args.get("reply") or ""),
        "timeSaved": {
            "minutes": min(MAX_TIME_SAVED_MINUTES, max(0, minutes)),
            "basis": str(args["time_saved_basis"]),
        },
    }

    ctx.finish(outcome)
    return "Delivered."


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


def _datadog(handler: Handler) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return handler(args, ctx)
        except datadog.DatadogError as exc:
            raise ToolError(str(exc)) from None

    return wrapped


def _datadog_site() -> str:
    site = datadog.load_state().get("site")
    if not site:
        raise ToolError("Datadog is not connected.")
    return site


def _datadog_scope(args: dict[str, Any], ctx: ToolContext) -> str:
    _, scope = datadog.resolve_scope(args.get("instance"), ctx.instance, args.get("role"))
    return scope


def _datadog_window(args: dict[str, Any], default: str) -> tuple[int, int]:
    return datadog.to_ms(args.get("from"), default), datadog.to_ms(args.get("to"), "now")


def _log_patterns(query: str, start: int, end: int) -> str:
    rows = datadog.search_logs(query, start, end, LOG_PATTERN_SCAN)
    groups = datadog.top_patterns(rows, LOG_PATTERN_GROUPS)
    if not groups:
        return "No logs matched."

    lines = [f"- {g['count']}x {g['pattern']}\n  e.g. [{g['last']} {g['service']}] {g['example']}" for g in groups]
    more = f" (first {LOG_PATTERN_SCAN} scanned)" if len(rows) >= LOG_PATTERN_SCAN else ""
    return f"{len(rows)} logs{more} in {len(groups)} groups:\n" + "\n".join(lines)


def _log_lines(query: str, start: int, end: int, limit: int) -> str:
    rows = datadog.search_logs(query, start, end, limit)
    if not rows:
        return "No logs matched."

    lines = [
        f"{r['time']} {r['status'] or '-'} {r['host'] or '-'} {r['service'] or '-'}: "
        f"{r['message'][: datadog.MESSAGE_CHARS]}"
        for r in rows
    ]
    return f"{len(rows)} newest:\n" + "\n".join(lines)


def _datadog_logs(args: dict[str, Any], ctx: ToolContext) -> str:
    query = datadog.combine(_datadog_scope(args, ctx), str(args.get("query") or ""))
    start, end = _datadog_window(args, "now-1h")
    link = datadog.logs_link(_datadog_site(), query, start, end)
    if args.get("patterns"):
        body = _log_patterns(query, start, end)
    else:
        limit = max(1, min(int(args.get("limit") or DEFAULT_LOG_LINES), datadog.MAX_LOG_LINES))
        body = _log_lines(query, start, end, limit)

    head = f"Datadog logs, query: {query}, {datadog.iso(start)} to {datadog.iso(end)} UTC"
    return clip(f"{head}\n{body}\nOpen: {link}", ctx, "logs")


def _metric_query(raw: str, scope: str) -> str:
    query = raw.strip()
    if not query:
        raise ToolError('Give a metric query, e.g. "avg:jvm.heap_memory".')

    tags = datadog.metric_scope(scope) if scope else "*"
    if "{$scope}" in query:
        return query.replace("{$scope}", "{" + tags + "}")
    if "{" not in query:
        return f"{query}{{{tags}}}"
    return query


def _datadog_metrics(args: dict[str, Any], ctx: ToolContext) -> str:
    query = _metric_query(str(args["query"]), _datadog_scope(args, ctx))
    start, end = _datadog_window(args, "now-4h")
    series = datadog.query_metric(query, start, end)
    if not series:
        return f"No data for {query} between {datadog.iso(start)} and {datadog.iso(end)} UTC."

    hidden = len(series) - MAX_SERIES_SHOWN
    more = f"\n({hidden} more series not shown)" if hidden > 0 else ""
    body = "\n".join(datadog.summarize_series(s) for s in series[:MAX_SERIES_SHOWN])
    return clip(f"{query}, {datadog.iso(start)} to {datadog.iso(end)} UTC:\n{body}{more}", ctx, "metrics")


def _datadog_monitors(args: dict[str, Any], ctx: ToolContext) -> str:
    scope = _datadog_scope(args, ctx)
    rows = datadog.monitors_for(scope, include_ok=bool(args.get("include_ok")))
    if not rows:
        return f"No {'' if args.get('include_ok') else 'alerting or warning '}monitors for {scope or 'the org'}."

    base = datadog.app_url(_datadog_site())
    lines = []
    for m in rows[:MAX_MONITORS_SHOWN]:
        groups = f" groups: {', '.join(m['groups'])}" if m["groups"] else ""
        lines.append(f"[{m['state']}] {m['name']} ({base}/monitors/{m['id']}){groups}")
    return clip(f"Monitors for {scope or 'the org'}:\n" + "\n".join(lines), ctx, "monitors")


def _datadog_events(args: dict[str, Any], ctx: ToolContext) -> str:
    query = datadog.combine(_datadog_scope(args, ctx), str(args.get("query") or ""))
    start, end = _datadog_window(args, "now-24h")
    rows = datadog.events_for(query, start, end, int(args.get("limit") or DEFAULT_EVENTS))
    if not rows:
        return f"No events for {query} between {datadog.iso(start)} and {datadog.iso(end)} UTC."

    lines = [
        f"{r['time']} [{r['source'] or '-'}{' ' + r['status'] if r['status'] else ''}] "
        f"{r['title']}{': ' + r['message'] if r['message'] and r['message'] != r['title'] else ''}"
        for r in rows
    ]
    return clip(f"Events for {query}:\n" + "\n".join(lines), ctx, "events")


def _error_spans(query: str, start: int, end: int, limit: int, ctx: ToolContext) -> str:
    rows = datadog.error_spans(query, start, end, limit)
    if not rows:
        return f"No error spans for {query}."

    lines = [f"{r['time']} {r['service']} {r['resource']}: {r['error']} (trace {r['trace']})" for r in rows]
    return clip(f"Error spans for {query}:\n" + "\n".join(lines), ctx, "spans")


def _slow_endpoints(query: str, start: int, end: int, limit: int) -> str:
    rows = datadog.slow_endpoints(query, start, end, limit)
    if not rows:
        return f"No spans for {query}."

    lines = [f"p95 {r['p95Ms']} ms, {r['count']} calls: {r['resource']}" for r in rows]
    return f"Slowest endpoints by p95 for {query}:\n" + "\n".join(lines)


def _datadog_apm(args: dict[str, Any], ctx: ToolContext) -> str:
    query = datadog.combine(_datadog_scope(args, ctx), str(args.get("query") or ""))
    start, end = _datadog_window(args, "now-1h")
    if args.get("mode") == "errors":
        return _error_spans(query, start, end, int(args.get("limit") or DEFAULT_ERROR_SPANS), ctx)
    return _slow_endpoints(query, start, end, int(args.get("limit") or DEFAULT_SLOW_ENDPOINTS))


def _ov_label(a: dict[str, Any]) -> str:
    at = f" @ {a['instance']}" if a.get("instance") else ""
    return f"ov {' '.join(str(x) for x in (a.get('args') or [])[:LABEL_ARGS])}{at}"


INSTANCE = _str("Instance alias or host. Defaults to the run's instance, if one is set.")

TOOLS = [
    Tool(
        "ov_case",
        "Read a support case from trackor.onevizion.com: every field, the full chat, and all "
        "attachments (saved to the workspace; open each with read_file). Also sets the run's "
        "instance to the case's affected instance (C_WEBSITE).",
        {"case": _str("Case number (e.g. 193915) or a trackor.onevizion.com case link")},
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
            "args": _strings(
                'Arguments after "ov -i <alias>", e.g. ["request","GET","/v3/trackors/123","-q","fields=A,B"]'
            ),
        },
        ["args"],
        _ov_label,
        lambda a, ctx: run_ov_tool(list(a["args"]), a.get("instance"), ctx),
    ),
    Tool(
        "ov_map",
        "Look an object up on the Instance map: what a trackor type, field, rule, automation, "
        "import, report, notification, workflow, module or DB package is linked to (relations, "
        "fields, triggers, packages it calls, and objects its code references by quoted name, "
        "config id or id.* object reference). Fast, no SQL needed. Builds the map on first use "
        "(about a minute). Use it before changing anything to see what depends on it.",
        {
            "instance": INSTANCE,
            "object": _str("Name or id of the object, e.g. C_STATUS, a rule name, or 100121663"),
        },
        ["object"],
        lambda a: f"map {a.get('object')}{' @ ' + a['instance'] if a.get('instance') else ''}",
        _ov_map,
    ),
    Tool(
        "ov_sql",
        "Run a read-only SELECT (or WITH) on an instance database through the platform's Test "
        "SQL endpoint. Max 1000 rows.",
        {
            "instance": INSTANCE,
            "query": _str("A single SELECT statement, no trailing semicolon"),
            "rows": _int("Row limit, default 100, max 1000"),
        },
        ["query"],
        lambda a: (
            f"SQL{' @ ' + a['instance'] if a.get('instance') else ''}: "
            + re.sub(r"\s+", " ", str(a.get("query", "")))[:LABEL_CHARS]
        ),
        _ov_sql,
    ),
    Tool(
        "ov_search",
        "Search trackors of a type with a condition (equal, not_equal, greater, less, within, "
        "is_null, is_not_null, and/or, parentheses). String and date values in double quotes.",
        {
            "instance": INSTANCE,
            "trackor_type": _str("Trackor type name"),
            "fields": _strings("Field names to return"),
            "condition": _str('e.g. equal(TRACKOR_KEY, "P-100") and greater(F_DATE, "2026-01-01")'),
            "limit": _int("Max rows, default 50"),
        },
        ["trackor_type", "fields", "condition"],
        lambda a: f"search {a.get('trackor_type')}: {str(a.get('condition', ''))[:LABEL_CHARS]}",
        _ov_search,
    ),
    Tool(
        "read_skill",
        "Read a skill: the full guide for an area listed under Skills in the prompt. Read every skill "
        "that covers the task before working on it.",
        {"name": _str("Skill name, as listed under Skills")},
        ["name"],
        lambda a: f"skill {a.get('name')}",
        _read_skill,
    ),
    Tool(
        "read_file",
        "Read a file from this run's workspace: attachments the user sent, files saved with "
        "ov --out, and spilled tool output. Images are shown to you; emails are expanded to text.",
        {
            "path": _str("Path relative to the workspace, or an attachment name"),
            "start": _int("First line, 1-based"),
            "end": _int("Last line"),
        },
        ["path"],
        lambda a: f"read {a.get('path')}",
        _read_file,
    ),
    Tool(
        "source_search",
        'git grep (extended regex) in a configured source (code or docs folder) or a cloned repo ("repo:<name>").',
        {
            "source": _str('Source name, or "repo:<name>" for a repo from github_clone'),
            "pattern": _str("Extended regex"),
            "path": _str('Optional pathspec, e.g. "db/*" or "*.py"'),
            "ignore_case": {"type": "boolean"},
        },
        ["source", "pattern"],
        lambda a: f"grep {a.get('source')}: {a.get('pattern')}",
        _source_search,
    ),
    Tool(
        "source_read",
        "Read a file, or list a directory, from a source or cloned repo.",
        {
            "source": _str('Source name or "repo:<name>"'),
            "path": _str("Path inside the source; empty string for its root"),
            "start": _int("First line"),
            "end": _int("Last line"),
        },
        ["source", "path"],
        lambda a: f"read {a.get('source')}/{a.get('path')}",
        _source_read,
    ),
    Tool(
        "github_clone",
        "Clone or update a GitHub (or any git) repository, e.g. a Vizion Hub module from "
        "MODULE.GIT_REPO_URL, so it can be searched with source_search and read with "
        'source_read as "repo:<name>". Uses this computer\'s git and its credentials. '
        "Returns the file list.",
        {"url": _str("Repository URL")},
        ["url"],
        lambda a: f"clone {str(a.get('url', '')).rstrip('/').rsplit('/', 1)[-1]}",
        _github_clone,
    ),
    Tool(
        "propose_change",
        "Show a proposed change as a diff card. One call per object. Nothing is applied. Pass "
        "the whole object text in both before and after.",
        {
            "title": _str("Short title"),
            "entity_type": _str("rule, report, automation, module file, data fix, field, ..."),
            "entity_id": _str("ID if known"),
            "entity_name": _str("Name as shown in the admin UI"),
            "instance": _str("Instance host"),
            "link": _str(
                "Direct URL to the object, only for types without a known edit form (rules, "
                "reports, automations and trackors get one automatically from entity_id)"
            ),
            "language": {
                "type": "string",
                "enum": [
                    "sql",
                    "plsql",
                    "python",
                    "javascript",
                    "typescript",
                    "json",
                    "xml",
                    "html",
                    "text",
                ],
            },
            "before": _str(
                "The COMPLETE current text exactly as fetched, never a fragment. Empty only "
                "for new objects or data fixes."
            ),
            "after": _str("The COMPLETE proposed text, same scope as before"),
            "what": _str("What changes, one sentence"),
            "why": _str("Why, one sentence"),
            "how": _str("How to apply it, one sentence"),
        },
        ["title", "entity_type", "language", "after", "what", "why", "how"],
        lambda a: f"propose {a.get('entity_type')}: {a.get('title')}",
        _propose_change,
        silent=True,
    ),
    Tool(
        "ask_user",
        "Ask the user a multiple-choice question when you truly cannot proceed (which "
        "instance, which of several objects, missing access). Blocks until answered.",
        {
            "question": _str("One short question"),
            "options": _strings("2-5 short options; the user can also type their own"),
            "multiple": {"type": "boolean"},
        },
        ["question", "options"],
        lambda a: f"ask: {str(a.get('question', ''))[:LABEL_CHARS]}",
        _ask_user,
        silent=True,
    ),
    Tool(
        "finish",
        "Deliver the result of an investigation. Call once at the end; skip it for quick "
        "questions answered in chat. The user may ask follow-ups afterwards.",
        {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": _str("The finding in a few words"),
                        "verdict": {
                            "type": "string",
                            "enum": ["fix", "fixed", "user_action", "expected", "info", "unknown"],
                            "description": "fix = a change is still needed; fixed = already "
                            "resolved and verified; user_action = someone must act; expected = "
                            "works as designed; info = an answer or fact",
                        },
                        "summary": _str("Short answer to what was asked, plain language"),
                        "still_happening": {"type": "boolean"},
                        "evidence": _strings(
                            "1-4 short facts you verified yourself on the instance, e.g. "
                            '"Rule 100024528 is_enabled = 0 (checked 10/01)"'
                        ),
                    },
                    "required": ["title", "verdict", "summary", "evidence"],
                    "additionalProperties": False,
                },
            },
            "existing": {
                "type": "array",
                "description": "Closest existing Issues / Issue Tasks found on trackor",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": _str("Issue or task key"),
                        "title": _str("Summary"),
                        "covers": {"type": "string", "enum": ["yes", "partly", "no"]},
                        "note": _str("One short sentence"),
                        "link": _str("URL"),
                    },
                    "required": ["key", "title", "covers"],
                    "additionalProperties": False,
                },
            },
            "unrelated": _strings("Unrelated problems noticed, one sentence each"),
            "reply": _str(
                "Working a case: the case chat comment in the reply style - short paragraphs "
                "separated by blank lines: update, what the problem was, what I did, current "
                "status and next step. Otherwise a short message the user can forward, or empty."
            ),
            "time_saved_minutes": _int(
                "Realistic minutes an experienced TCE would have spent doing this exact "
                "investigation and write-up by hand (opening each system, writing the queries, "
                "reading the code, dead ends, writing the fix and reply), minus about 10 minutes "
                "to review your result. Base it on what the work actually needed, not on how "
                "many tool calls you made. Do not inflate."
            ),
            "time_saved_basis": _str(
                'One short sentence: what made it take that long by hand, e.g. "Tracing the '
                'rule through 3 packages and comparing 2 weeks of run logs."'
            ),
        },
        ["findings", "time_saved_minutes", "time_saved_basis"],
        lambda _: "finish",
        _finish,
        silent=True,
    ),
]

WINDOW_FROM = _str('Start: "now-2h", "now-30m", "now-7d", an ISO time (UTC) or epoch')
WINDOW_TO = _str('End, default "now"')
DATADOG_INSTANCE = _str(
    "Instance alias or host; its Datadog filter (host or service tags) is applied. Defaults to the run's instance."
)
ROLE = _str(
    "Only servers of this role, named after the machine name without its number (e.g. web for "
    "web01, app for app01); default all. The instance's roles are listed in the prompt."
)


def _datadog_label(kind: str) -> Callable[[dict[str, Any]], str]:
    def label(a: dict[str, Any]) -> str:
        what = a.get("query") or a.get("mode") or ""
        at = f" @ {a['instance']}" if a.get("instance") else ""
        span = f" {a['from']}" if a.get("from") else ""
        return f"Datadog {kind}{': ' + str(what)[:LABEL_CHARS] if what else ''}{span}{at}"

    return label


DATADOG_TOOLS = {
    "datadog_logs": "logs",
    "datadog_metrics": "metrics",
    "datadog_monitors": "monitors",
    "datadog_events": "events",
    "datadog_apm": "apm",
}

TOOLS += [
    Tool(
        "datadog_logs",
        "Search Datadog logs for an instance in a time window: newest matching lines, or with "
        "patterns=true the most common message groups (scans up to 500). Use Datadog log query "
        'syntax, e.g. status:error, service:x, "OutOfMemory", @http.status_code:500.',
        {
            "instance": DATADOG_INSTANCE,
            "role": ROLE,
            "query": _str('Extra log query, e.g. status:error "deadlock"'),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "limit": _int(f"Lines to return, default 30, max {datadog.MAX_LOG_LINES}"),
            "patterns": {"type": "boolean", "description": "Group messages instead of listing"},
        },
        [],
        _datadog_label("logs"),
        _datadog(_datadog_logs),
    ),
    Tool(
        "datadog_metrics",
        "Query a Datadog metric for an instance and get min, avg, max, latest and a sample of "
        "points per series. Give an aggregation and metric, e.g. avg:system.cpu.user, "
        "avg:jvm.heap_memory, max:system.disk.in_use; the instance filter is added as the scope "
        'unless the query has its own {...} scope. Add "by {host}" to split by host.',
        {
            "instance": DATADOG_INSTANCE,
            "role": ROLE,
            "query": _str("Metric query, e.g. avg:jvm.heap_memory or avg:system.cpu.user by {host}"),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
        },
        ["query"],
        _datadog_label("metric"),
        _datadog(_datadog_metrics),
    ),
    Tool(
        "datadog_monitors",
        "List Datadog monitors for an instance that are alerting, warning or have no data "
        "(include_ok=true for all), with links.",
        {"instance": DATADOG_INSTANCE, "include_ok": {"type": "boolean"}},
        [],
        _datadog_label("monitors"),
        _datadog(_datadog_monitors),
    ),
    Tool(
        "datadog_events",
        "List Datadog events for an instance in a time window: deploys, restarts, alerts, config changes.",
        {
            "instance": DATADOG_INSTANCE,
            "role": ROLE,
            "query": _str("Extra event query, optional"),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "limit": _int("Max events, default 30"),
        },
        [],
        _datadog_label("events"),
        _datadog(_datadog_events),
    ),
    Tool(
        "datadog_apm",
        "Datadog APM for an instance: the slowest endpoints by p95 latency (mode=slowest) or "
        "recent error spans with their traces (mode=errors).",
        {
            "instance": DATADOG_INSTANCE,
            "role": ROLE,
            "mode": {"type": "string", "enum": ["slowest", "errors"]},
            "query": _str("Extra span query, e.g. service:x or resource_name:*Import*"),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "limit": _int("Max rows"),
        },
        [],
        _datadog_label("APM"),
        _datadog(_datadog_apm),
    ),
]


def _pagerduty(handler: Handler) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return handler(args, ctx)
        except (pagerduty.PagerDutyError, datadog.DatadogError) as exc:
            raise ToolError(str(exc)) from None

    return wrapped


def _incident_line(i: dict[str, Any]) -> str:
    who = f", assigned {', '.join(i['assignees'])}" if i["assignees"] else ""
    pri = f" {i['priority']}" if i["priority"] else ""
    return (
        f"#{i['number']} [{i['status']}, {i['urgency']}{pri}] {i['title']}\n"
        f"  service {i['service']}, created {pagerduty.short_time(i['created'])} UTC, "
        f"last change {pagerduty.short_time(i['changed'])}{who}\n  {i['url']}"
    )


def _pagerduty_rows(args: dict[str, Any], ctx: ToolContext, default: str) -> tuple[str, list]:
    alias = "" if args.get("all_instances") else pagerduty.resolve_host(args.get("instance"), ctx.instance)
    start = datadog.to_ms(args.get("from"), default)
    end = datadog.to_ms(args.get("to"), "now")
    statuses = [s for s in (args.get("statuses") or []) if s in ("triggered", "acknowledged", "resolved")]
    rows = pagerduty.incidents(start, end, statuses or None)
    if alias:
        rows = pagerduty.for_instance(rows, alias)

    found = pagerduty.find_instance(alias) if alias else None
    where = found["host"] if found else "all instances"
    head = f"PagerDuty incidents for {where}, {pagerduty.iso_utc(start)} to {pagerduty.iso_utc(end)}"
    if statuses:
        head += f", status {'/'.join(statuses)}"
    return head, rows


def _pagerduty_incidents(args: dict[str, Any], ctx: ToolContext) -> str:
    head, rows = _pagerduty_rows(args, ctx, "now-7d")
    text = str(args.get("query") or "").strip().lower()
    if text:
        rows = [r for r in rows if text in f"{r['title']} {r['service']} {r['text']}".lower()]
        head += f", matching {text!r}"
    if not rows:
        return f"{head}\nNone."

    limit = max(1, min(int(args.get("limit") or DEFAULT_INCIDENTS), pagerduty.MAX_INCIDENTS))
    more = f"\n({len(rows) - limit} more not shown)" if len(rows) > limit else ""
    body = "\n".join(_incident_line(r) for r in rows[:limit])
    return clip(f"{head}\n{body}{more}", ctx, "incidents")


def _alert_lines(alerts: list[dict[str, Any]]) -> list[str]:
    lines = ["", "Alerts:"]
    for a in alerts:
        lines.append(f"- {pagerduty.short_time(a['time'])} [{a['status']}] {a['summary']}")
        if a["details"]:
            lines.append("  " + a["details"].replace("\n", "\n  "))
    return lines


def _pagerduty_incident(args: dict[str, Any], ctx: ToolContext) -> str:
    i = pagerduty.incident_detail(str(args["incident"]))
    lines = [_incident_line(i), "", "Timeline:"]
    lines += [f"- {pagerduty.short_time(e['time'])} {e['type']}: {e['summary']}" for e in i["timeline"]] or ["- none"]
    if i["alerts"]:
        lines += _alert_lines(i["alerts"])
    if i["notes"]:
        lines += ["", "Notes:"]
        lines += [f"- {pagerduty.short_time(n['time'])} {n['by']}: {n['text']}" for n in i["notes"]]
    return clip("\n".join(lines), ctx, "incident")


def _instance_policies(alias: str) -> list[str]:
    end = int(time.time() * 1000)
    rows = pagerduty.for_instance(pagerduty.incidents(end - ONCALL_LOOKBACK_DAYS * DAY_MS, end), alias)
    return [r["policy"] for r in rows if r["policy"]]


def _pagerduty_oncall(args: dict[str, Any], ctx: ToolContext) -> str:
    alias = pagerduty.resolve_host(args.get("instance"), ctx.instance)
    at = datadog.to_ms(args.get("at"), "now") if args.get("at") else None
    policies: list[str] = []
    where = "every escalation policy"
    if alias:
        policies = _instance_policies(alias)
        found = pagerduty.find_instance(alias)
        where = found["host"] if found else alias
        if not policies:
            return (
                f"No PagerDuty incident for {where} in the last {ONCALL_LOOKBACK_DAYS} days, so no escalation "
                "policy is known for it. Call again without instance for everyone on call."
            )

    rows = pagerduty.oncall(policies, at)
    if not rows:
        return f"Nobody is on call for {where}."

    lines = [
        f"- level {r['level']} {r['user']} ({r['policy']}"
        f"{', ' + r['schedule'] if r['schedule'] else ''}"
        f"{', until ' + pagerduty.short_time(r['until']) if r['until'] else ''})"
        for r in rows
    ]
    when = f"at {pagerduty.iso_utc(at)}" if at else "now"
    return f"On call {when} for {where}:\n" + "\n".join(lines)


def _pagerduty_label(kind: str) -> Callable[[dict[str, Any]], str]:
    def label(a: dict[str, Any]) -> str:
        what = a.get("incident") or a.get("query") or ""
        at = f" @ {a['instance']}" if a.get("instance") else ""
        return f"PagerDuty {kind}{': ' + str(what)[:LABEL_CHARS] if what else ''}{at}"

    return label


PAGERDUTY_TOOLS = {
    "pagerduty_incidents": "incidents",
    "pagerduty_incident": "incidents",
    "pagerduty_oncall": "oncall",
}

TOOLS += [
    Tool(
        "pagerduty_incidents",
        "List PagerDuty incidents for an instance in a time window, newest first: number, "
        "status, urgency, title, service, assignee and link. Incidents are tied to an instance "
        "by the website in their alert (OV monitoring's website field, or the host named in a "
        "Datadog alert). Filter by statuses and a text query; all_instances=true lists all.",
        {
            "instance": _str("Instance alias or host. Defaults to the run's instance."),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "statuses": {
                "type": "array",
                "items": {"type": "string", "enum": ["triggered", "acknowledged", "resolved"]},
            },
            "query": _str("Text the title, service or alert details must contain"),
            "all_instances": {"type": "boolean"},
            "limit": _int(f"Max incidents, default 25, max {pagerduty.MAX_INCIDENTS}"),
        },
        [],
        _pagerduty_label("incidents"),
        _pagerduty(_pagerduty_incidents),
    ),
    Tool(
        "pagerduty_incident",
        "Read one PagerDuty incident in full: status, timeline (triggered, acknowledged, "
        "escalated, resolved), alerts with their details (Datadog monitor alerts carry the "
        "monitor and its query) and notes.",
        {"incident": _str("Incident number (e.g. 12345), id or PagerDuty link")},
        ["incident"],
        _pagerduty_label("incident"),
        _pagerduty(_pagerduty_incident),
    ),
    Tool(
        "pagerduty_oncall",
        "Who is on call, now or at a given time, by escalation level: for the escalation "
        "policies that paged about an instance in the last 30 days, or for every policy when "
        "no instance is given.",
        {
            "instance": _str("Instance alias or host; omit for every policy"),
            "at": _str('A time, e.g. "now-2h" or an ISO time (UTC); default now'),
        },
        [],
        _pagerduty_label("on call"),
        _pagerduty(_pagerduty_oncall),
    ),
]

TOOL_SPECS = [t.spec for t in TOOLS if t.name not in DATADOG_TOOLS and t.name not in PAGERDUTY_TOOLS]

TOOL_GROUPS: list[tuple[str, str, list[str]]] = [
    ("OV CLI", "signed-in OneVizion instances", ["ov", "ov_sql", "ov_search", "ov_map", "ov_case"]),
    ("Sources", "folders on this computer and cloned repos", ["source_search", "source_read"]),
    ("GitHub", "module and project repositories", ["github_clone"]),
    ("Datadog", "logs, metrics, monitors, events and APM", list(DATADOG_TOOLS)),
    ("PagerDuty", "incidents and on-call", list(PAGERDUTY_TOOLS)),
    (
        "This run",
        "workspace files, proposed changes, questions and the result",
        ["read_skill", "read_file", "propose_change", "ask_user", "finish"],
    ),
]


def tool_specs() -> list[dict[str, Any]]:
    specs = list(TOOL_SPECS)
    for linked, allowed, names in (
        (datadog.connected, datadog.permissions, DATADOG_TOOLS),
        (pagerduty.connected, pagerduty.permissions, PAGERDUTY_TOOLS),
    ):
        if linked():
            areas = allowed()
            specs += [t.spec for t in TOOLS if t.name in names and areas[names[t.name]]]
    return specs


TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def tool_named(name: str) -> Tool | None:
    return TOOLS_BY_NAME.get(name)
