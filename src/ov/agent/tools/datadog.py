from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ov.agent.integrations import datadog
from ov.agent.tools.base import (
    Handler,
    Tool,
    ToolContext,
    ToolError,
    brief,
    clip,
    int_param,
    raising_tool_errors,
    string_param,
)

LOG_PATTERN_SCAN = 500
LOG_PATTERN_GROUPS = 15
DEFAULT_LOG_LINES = 30
MAX_MONITORS_SHOWN = 60
MAX_SERIES_SHOWN = 10
DEFAULT_EVENTS = 30
DEFAULT_ERROR_SPANS = 25
DEFAULT_SLOW_ENDPOINTS = 10

_SCOPED_QUERY = re.compile(r"(?<![\w.])(host|service):\S", re.IGNORECASE)

WINDOW_FROM = string_param('Start: "now-2h", "now-30m", "now-7d", an ISO time (UTC) or epoch')
WINDOW_TO = string_param('End, default "now"')
DATADOG_INSTANCE = string_param(
    "Instance alias or host; its Datadog filter (host or service tags) is applied. Defaults to the run's instance."
)
ROLE = string_param(
    "Only servers of this role, named after the machine name without its number (e.g. web for "
    "web01, app for app01); default all. The instance's roles are listed in the prompt."
)

AREA_OF_TOOL = {
    "dd_logs": "logs",
    "dd_metrics": "metrics",
    "dd_monitors": "monitors",
    "dd_events": "events",
    "dd_apm": "apm",
}


def _datadog(handler: Handler) -> Handler:
    return raising_tool_errors(handler, datadog.DatadogError)


def _datadog_site() -> str:
    site = datadog.load_state().get("site")
    if not site:
        raise ToolError("Datadog is not connected.")
    return site


def _datadog_scope(args: dict[str, Any], ctx: ToolContext) -> str:
    if _SCOPED_QUERY.search(str(args.get("query") or "")):
        return ""
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
    alias, scope = datadog.resolve_scope(args.get("instance"), ctx.instance)
    databases = datadog.known_databases(alias) if scope else []
    needles = datadog.database_needles(alias) if databases else []
    rows = datadog.monitors_for(scope, include_ok=bool(args.get("include_ok")), database_needles=needles)

    target = scope or "the org"
    if databases:
        names = [f"{d['id']} ({d['endpoint']})" if d["endpoint"] else d["id"] for d in databases]
        target += f" and databases {', '.join(names)}"

    if not rows:
        return f"No {'' if args.get('include_ok') else 'alerting or warning '}monitors for {target}."

    base = datadog.app_url(_datadog_site())
    lines = []
    for m in rows[:MAX_MONITORS_SHOWN]:
        groups = f" groups: {', '.join(m['groups'])}" if m["groups"] else ""
        lines.append(f"[{m['state']}] {m['name']} ({base}/monitors/{m['id']}){groups}")

    return clip(f"Monitors for {target}:\n" + "\n".join(lines), ctx, "monitors")


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


def _datadog_label(kind: str) -> Callable[[dict[str, Any]], str]:
    def label(a: dict[str, Any]) -> str:
        what = a.get("query") or a.get("mode") or ""
        at = f" @ {a['instance']}" if a.get("instance") else ""
        span = f" {a['from']}" if a.get("from") else ""
        return f"Datadog {kind}{': ' + brief(what) if what else ''}{span}{at}"

    return label


TOOLS = [
    Tool(
        "dd_logs",
        "Search Datadog logs for an instance in a time window: newest matching lines, or with "
        "patterns=true the most common message groups (scans up to 500). Use Datadog log query "
        'syntax, e.g. status:error, service:x, "OutOfMemory", @http.status_code:500.',
        {
            "instance": DATADOG_INSTANCE,
            "role": ROLE,
            "query": string_param('Extra log query, e.g. status:error "deadlock"'),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "limit": int_param(f"Lines to return, default 30, max {datadog.MAX_LOG_LINES}"),
            "patterns": {"type": "boolean", "description": "Group messages instead of listing"},
        },
        [],
        _datadog_label("logs"),
        _datadog(_datadog_logs),
    ),
    Tool(
        "dd_metrics",
        "Query a Datadog metric for an instance and get min, avg, max, latest and a sample of "
        "points per series. Give an aggregation and metric, e.g. avg:system.cpu.user, "
        "avg:jvm.heap_memory, max:system.disk.in_use; the instance filter is added as the scope "
        'unless the query has its own {...} scope. Add "by {host}" to split by host. Databases '
        "are not hosts: query aws.rds.* with {dbinstanceidentifier:<id>} and oracle.* with "
        "{server:<endpoint>}; dd_monitors names the instance's databases.",
        {
            "instance": DATADOG_INSTANCE,
            "role": ROLE,
            "query": string_param("Metric query, e.g. avg:jvm.heap_memory or avg:system.cpu.user by {host}"),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
        },
        ["query"],
        _datadog_label("metric"),
        _datadog(_datadog_metrics),
    ),
    Tool(
        "dd_monitors",
        "List Datadog monitors for an instance that are alerting, warning or have no data "
        "(include_ok=true for all), with links.",
        {"instance": DATADOG_INSTANCE, "include_ok": {"type": "boolean"}},
        [],
        _datadog_label("monitors"),
        _datadog(_datadog_monitors),
    ),
    Tool(
        "dd_events",
        "List Datadog events for an instance in a time window: deploys, restarts, alerts, config changes.",
        {
            "instance": DATADOG_INSTANCE,
            "role": ROLE,
            "query": string_param("Extra event query, optional"),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "limit": int_param("Max events, default 30"),
        },
        [],
        _datadog_label("events"),
        _datadog(_datadog_events),
    ),
    Tool(
        "dd_apm",
        "Datadog APM for an instance: the slowest endpoints by p95 latency (mode=slowest) or "
        "recent error spans with their traces (mode=errors).",
        {
            "instance": DATADOG_INSTANCE,
            "role": ROLE,
            "mode": {"type": "string", "enum": ["slowest", "errors"]},
            "query": string_param("Extra span query, e.g. service:x or resource_name:*Import*"),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "limit": int_param("Max rows"),
        },
        [],
        _datadog_label("APM"),
        _datadog(_datadog_apm),
    ),
]


def offered() -> list[Tool]:
    if not datadog.connected():
        return []
    areas = datadog.permissions()
    return [t for t in TOOLS if areas[AREA_OF_TOOL[t.name]]]
