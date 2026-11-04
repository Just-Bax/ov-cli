from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import quote

from ov.agent.integrations.datadog.apm import slow_endpoints, traffic
from ov.agent.integrations.datadog.connection import (
    DatadogError,
    app_url,
    health_cache,
    load_state,
    permissions,
    stored,
)
from ov.agent.integrations.datadog.databases import (
    ORACLE_TAG,
    RDS_ENDPOINT_SUFFIX,
    RDS_TAG,
    database_needles,
    databases_for,
)
from ov.agent.integrations.datadog.hosts import filter_for, hosts_in, role_of
from ov.agent.integrations.datadog.queries import (
    combine,
    events_for,
    log_timeseries,
    logs_link,
    metric_scope,
    monitors_for,
    parallel,
    query_metric,
    search_logs,
    tag_filter,
    tag_of,
    top_patterns,
)
from ov.agent.storage.db import now_ms

HEALTH_LOG_SAMPLE = 300
HEALTH_EVENTS = 15
HEALTH_ENDPOINTS = 8
CHART_POINTS = 60
SERVER_POINTS = 30

RANGES = {"1h": (3600, "1m"), "24h": (86400, "30m"), "7d": (604800, "6h")}
METRICS = [
    ("cpu", "avg:system.cpu.user{%s} by {host}"),
    ("memory", "avg:system.mem.pct_usable{%s} by {host}*100"),
    ("disk", "max:system.disk.in_use{%s} by {host}*100"),
    ("load", "avg:system.load.norm.1{%s} by {host}"),
    ("heap", "avg:jvm.heap_memory{%s} by {host}"),
]
DATABASE_METRICS = [
    ("cpu", RDS_TAG, "avg:aws.rds.cpuutilization{%(scope)s} by {dbinstanceidentifier}"),
    ("cpu", ORACLE_TAG, "avg:oracle.host_cpu_utilization{%(scope)s} by {server}"),
    ("memory", RDS_TAG, "avg:aws.rds.freeable_memory{%(scope)s} by {dbinstanceidentifier}"),
    (
        "storage",
        RDS_TAG,
        "100 - 100 * avg:aws.rds.free_storage_space{%(scope)s} by {dbinstanceidentifier} / "
        "avg:aws.rds.total_storage_space{%(scope)s} by {dbinstanceidentifier}",
    ),
    ("connections", RDS_TAG, "avg:aws.rds.database_connections{%(scope)s} by {dbinstanceidentifier}"),
    ("readLatency", RDS_TAG, "avg:aws.rds.read_latency{%(scope)s} by {dbinstanceidentifier}*1000"),
    ("writeLatency", RDS_TAG, "avg:aws.rds.write_latency{%(scope)s} by {dbinstanceidentifier}*1000"),
    ("activeSessions", ORACLE_TAG, "avg:oracle.active_sessions{%(scope)s} by {server}"),
    ("responseTime", ORACLE_TAG, "avg:oracle.service_response_time{%(scope)s} by {server}*1000"),
    ("sessions", ORACLE_TAG, "max:oracle.session_limit_usage{%(scope)s} by {server}"),
    ("tablespace", ORACLE_TAG, "max:oracle.tablespace.in_use{%(scope)s} by {server}"),
]
SECTION_AREAS = {
    "monitors": "monitors",
    "logs": "logs",
    "traffic": "apm",
    "servers": "metrics",
    "database": "metrics",
    "events": "events",
}
AREA_WORDS = {"monitors": "monitors", "logs": "logs", "apm": "APM traces", "metrics": "metrics", "events": "events"}


class Unavailable(DatadogError):
    pass


def window(range_key: str, end: int) -> tuple[int, str]:
    if range_key not in RANGES:
        raise DatadogError(f"Unknown range {range_key}. Use one of: {', '.join(RANGES)}.")
    seconds, interval = RANGES[range_key]
    return end - seconds * 1000, interval


def health_meta(alias: str, range_key: str) -> dict[str, Any]:
    end = now_ms()
    start, _ = window(range_key, end)
    scope = filter_for(alias)
    site = stored(load_state(), "site")
    base = app_url(site)

    return {
        "instance": alias,
        "range": range_key,
        "scope": scope,
        "from": start,
        "to": end,
        "appUrl": base,
        "links": {
            "logs": logs_link(site, combine(scope, "status:error"), start, end),
            "monitors": f"{base}/monitors/manage",
            "apm": f"{base}/apm/traces?query={quote(scope)}",
            "events": f"{base}/event/explorer?query={quote(scope)}",
            "metrics": f"{base}/infrastructure?filter={quote(scope)}",
        },
    }


def health_section(alias: str, range_key: str, section: str, end: int) -> dict[str, Any]:
    if section not in SECTION_AREAS:
        raise DatadogError(f"Unknown health section {section}.")

    key = (alias, range_key, section, end)
    cached = health_cache.get(key)
    if cached is not None:
        return cached

    area = SECTION_AREAS[section]
    if not permissions()[area]:
        raise Unavailable(f"The Datadog application key cannot read {AREA_WORDS[area]}.")

    scope = filter_for(alias)
    if not scope:
        raise Unavailable("This instance has no Datadog servers picked yet.")

    start, interval = window(range_key, end)
    result = SECTION_READERS[section](alias, scope, start, end, interval)
    health_cache.put(key, result)
    return result


def _monitors_section(alias: str, scope: str, _start: int, _end: int, _interval: str) -> dict[str, Any]:
    return {"monitors": monitors_for(scope, include_ok=True, database_needles=database_needles(alias))}


def _logs_section(_alias: str, scope: str, start: int, end: int, interval: str) -> dict[str, Any]:
    errors_query = combine(scope, "status:error")
    previous_start = start - (end - start)

    return parallel(
        {
            "errorSeries": partial(log_timeseries, errors_query, start, end, interval),
            "logSeries": partial(log_timeseries, scope, start, end, interval),
            "previousErrors": partial(_error_count, errors_query, previous_start, start, interval),
            "topErrors": lambda: top_patterns(search_logs(errors_query, start, end, HEALTH_LOG_SAMPLE)),
        }
    )


def _traffic_section(_alias: str, scope: str, start: int, end: int, interval: str) -> dict[str, Any]:
    return parallel(
        {
            "traffic": partial(traffic, scope, start, end, interval),
            "slowEndpoints": partial(slow_endpoints, scope, start, end, HEALTH_ENDPOINTS),
        }
    )


def _events_section(_alias: str, scope: str, start: int, end: int, _interval: str) -> dict[str, Any]:
    return {"events": events_for(scope, start, end, HEALTH_EVENTS)}


def _servers_section(_alias: str, scope: str, start: int, end: int, _interval: str) -> dict[str, Any]:
    tags = metric_scope(scope)
    found = parallel({name: partial(query_metric, template % tags, start, end) for name, template in METRICS})
    names = hosts_in(scope) or sorted({tag_of(s, "host") for series in found.values() for s in series} - {None})

    servers = []
    for name in names:
        metrics = {metric: _series_metric(found[metric], "host", name) for metric, _ in METRICS}
        servers.append({"host": name, "role": role_of(name), "metrics": {k: v for k, v in metrics.items() if v}})

    return {"servers": servers}


def _series_metric(series: list[dict[str, Any]], tag: str, value: str) -> dict[str, Any] | None:
    mine = next((s for s in series if tag_of(s, tag) == value and s["points"]), None)
    if mine is None:
        return None
    points = mine["points"]
    return {"latest": points[-1]["v"], "max": max(p["v"] for p in points), "points": downsample(points, SERVER_POINTS)}


def _database_section(alias: str, _scope: str, start: int, end: int, _interval: str) -> dict[str, Any]:
    databases = databases_for(alias)
    if not databases:
        raise Unavailable("No database is matched to this instance yet. Match it in Settings > Integrations > Datadog.")

    values = {
        RDS_TAG: [d["id"] for d in databases if not d["endpoint"] or d["endpoint"].endswith(RDS_ENDPOINT_SUFFIX)],
        ORACLE_TAG: [d["endpoint"] for d in databases if d["endpoint"]],
    }

    jobs = {
        f"{name}/{tag}": partial(query_metric, template % {"scope": tag_filter(tag, values[tag])}, start, end)
        for name, tag, template in DATABASE_METRICS
        if values[tag]
    }
    found = parallel(jobs)

    rows = []
    for db in databases:
        keys = {RDS_TAG: db["id"], ORACLE_TAG: db["endpoint"]}
        metrics: dict[str, dict[str, Any]] = {}
        for name, tag, _ in DATABASE_METRICS:
            series = found.get(f"{name}/{tag}")
            metric = None if name in metrics or series is None else _series_metric(series, tag, keys[tag])
            if metric:
                metrics[name] = metric

        rows.append({**db, "metrics": metrics})

    return {"databases": rows}


def _error_count(query: str, start: int, end: int, interval: str) -> float:
    return sum(p["v"] for p in log_timeseries(query, start, end, interval))


SECTION_READERS: dict[str, Callable[[str, str, int, int, str], dict[str, Any]]] = {
    "monitors": _monitors_section,
    "logs": _logs_section,
    "traffic": _traffic_section,
    "servers": _servers_section,
    "database": _database_section,
    "events": _events_section,
}


def downsample(points: list[dict[str, float]], buckets: int = CHART_POINTS) -> list[dict[str, float]]:
    if len(points) <= buckets:
        return points

    size = len(points) / buckets
    out = []
    for i in range(buckets):
        chunk = points[int(i * size) : int((i + 1) * size)]
        out.append({"t": chunk[0]["t"], "v": sum(p["v"] for p in chunk) / len(chunk)})

    return out
