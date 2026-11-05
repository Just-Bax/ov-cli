from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any
from urllib.parse import quote

from ov.agent.instances.ovproc import find_instance
from ov.agent.integrations.datadog.apm import latency_series, slow_endpoints
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
    databases_for,
)
from ov.agent.integrations.datadog.hosts import filter_for, hosts_in, role_of
from ov.agent.integrations.datadog.queries import (
    combine,
    instance_monitors,
    metric_scope,
    parallel,
    query_metric,
    tag_filter,
    tag_of,
)
from ov.agent.storage.db import now_ms

HEALTH_ENDPOINTS = 8
APM_OPERATION = "servlet.request"
CHART_POINTS = 60
SERVER_POINTS = 30

RANGES = {"1h": (3600, "1m"), "24h": (86400, "30m"), "7d": (604800, "6h")}
INTERVAL_SECONDS = {"1m": 60, "30m": 1800, "6h": 21600}
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
    "traffic": "apm",
    "servers": "metrics",
    "database": "metrics",
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
        "interval": INTERVAL_SECONDS[RANGES[range_key][1]] * 1000,
        "links": {
            "monitors": f"{base}/monitors/manage",
            "apm": f"{base}/apm/traces?query={quote(combine(scope, f'operation_name:{APM_OPERATION}'))}",
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
    hosts = hosts_in(scope) or []
    tags = [f"host:{h}" for h in hosts]
    for db in databases_for(alias):
        tags.append(f"{RDS_TAG}:{db['id']}")
        if db["endpoint"]:
            tags.append(f"{ORACLE_TAG}:{db['endpoint']}")

    return {"monitors": instance_monitors(tags, instance_site(alias))}


def instance_site(alias: str) -> str:
    found = find_instance(alias)
    if found is None:
        raise DatadogError(f"No signed-in instance matches {alias}.")
    return found["host"].split(":")[0]


def _traffic_section(_alias: str, scope: str, start: int, end: int, interval: str) -> dict[str, Any]:
    tags = metric_scope(scope)
    seconds = INTERVAL_SECONDS[interval]
    count = f".as_count().rollup(sum, {seconds})"
    spans = combine(scope, f"operation_name:{APM_OPERATION}")
    found = parallel(
        {
            "requests": partial(query_metric, f"sum:trace.{APM_OPERATION}.hits{{{tags}}}{count}", start, end),
            "errors": partial(query_metric, f"sum:trace.{APM_OPERATION}.errors{{{tags}}}{count}", start, end),
            "p95Ms": partial(latency_series, spans, start, end, interval),
            "slowEndpoints": partial(slow_endpoints, spans, start, end, HEALTH_ENDPOINTS),
        }
    )

    return {
        "requests": _points(found["requests"]),
        "errors": _points(found["errors"]),
        "p95Ms": found["p95Ms"],
        "slowEndpoints": found["slowEndpoints"],
    }


def _points(series: list[dict[str, Any]]) -> list[dict[str, float]]:
    return series[0]["points"] if series else []


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


SECTION_READERS: dict[str, Callable[[str, str, int, int, str], dict[str, Any]]] = {
    "monitors": _monitors_section,
    "traffic": _traffic_section,
    "servers": _servers_section,
    "database": _database_section,
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
