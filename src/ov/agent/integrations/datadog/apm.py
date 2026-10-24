from __future__ import annotations

from typing import Any

from ov.agent.integrations.datadog.connection import DatadogError, client, field
from ov.agent.integrations.datadog.queries import DETAIL_CHARS, combine, iso, points_of

SLOW_ENDPOINTS = 10
NS_PER_MS = 1e6


def spans_body(query: str, start: str, end: str, limit: int) -> dict[str, Any]:
    return {
        "data": {
            "type": "search_request",
            "attributes": {
                "filter": {"from": start, "to": end, "query": query},
                "page": {"limit": limit},
                "sort": "-timestamp",
            },
        }
    }


def _computes(attrs: dict[str, Any]) -> dict[str, Any]:
    compute = attrs.get("compute") or attrs.get("computes")
    if compute is None:
        raise DatadogError("Datadog returned an APM bucket without computed values.")
    return compute


def slow_endpoints(query: str, start: int, end: int, limit: int = SLOW_ENDPOINTS) -> list[dict[str, Any]]:
    by_p95 = {"aggregation": "pc95", "metric": "@duration", "order": "desc", "type": "measure"}
    body = {
        "data": {
            "type": "aggregate_request",
            "attributes": {
                "compute": [
                    {"aggregation": "pc95", "metric": "@duration", "type": "total"},
                    {"aggregation": "count", "type": "total"},
                ],
                "filter": {"from": str(start), "to": str(end), "query": query},
                "group_by": [{"facet": "resource_name", "limit": limit, "sort": by_p95}],
            },
        }
    }

    with client() as dd:
        data = dd.call("POST", "/api/v2/spans/analytics/aggregate", "apm", json=body)

    return [_endpoint_row(bucket) for bucket in field(data, "data")]


def _endpoint_row(bucket: dict[str, Any]) -> dict[str, Any]:
    attrs = field(bucket, "attributes")
    compute = _computes(attrs)

    return {
        "resource": str((attrs.get("by") or {}).get("resource_name") or "?"),
        "p95Ms": round(float(compute.get("c0") or 0) / NS_PER_MS, 1),
        "count": int(compute.get("c1") or 0),
    }


def error_spans(query: str, start: int, end: int, limit: int) -> list[dict[str, Any]]:
    body = spans_body(combine(query, "status:error"), str(start), str(end), limit)
    with client() as dd:
        data = dd.call("POST", "/api/v2/spans/events/search", "apm", json=body)
    return [_error_span_row(row) for row in field(data, "data")]


def _error_span_row(row: dict[str, Any]) -> dict[str, Any]:
    attrs = field(row, "attributes")
    custom = attrs.get("custom") or attrs.get("attributes") or {}
    error = custom.get("error") if isinstance(custom.get("error"), dict) else {}

    return {
        "time": iso(attrs.get("start_timestamp") or attrs.get("timestamp")),
        "service": attrs.get("service") or "",
        "resource": attrs.get("resource_name") or "",
        "error": str(error.get("message") or error.get("type") or "")[:DETAIL_CHARS],
        "trace": attrs.get("trace_id") or "",
    }


def _span_series(query: str, start: int, end: int, interval: str) -> dict[str, Any]:
    timeseries = {"type": "timeseries", "interval": interval}
    body = {
        "data": {
            "type": "aggregate_request",
            "attributes": {
                "compute": [
                    {"aggregation": "count", **timeseries},
                    {"aggregation": "pc95", "metric": "@duration", **timeseries},
                ],
                "filter": {"from": str(start), "to": str(end), "query": query},
            },
        }
    }

    with client() as dd:
        data = dd.call("POST", "/api/v2/spans/analytics/aggregate", "apm", json=body)

    buckets = field(data, "data")
    if not buckets:
        return {"requests": [], "p95Ms": []}

    compute = _computes(field(buckets[0], "attributes"))
    latency = [{"t": p["t"], "v": p["v"] / NS_PER_MS} for p in points_of(compute.get("c1", []))]
    return {"requests": points_of(compute.get("c0", [])), "p95Ms": latency}


def traffic(query: str, start: int, end: int, interval: str) -> dict[str, Any]:
    entry_spans = _span_series(combine(query, "@span.kind:server"), start, end, interval)
    if any(p["v"] for p in entry_spans["requests"]):
        return entry_spans
    return _span_series(query, start, end, interval)
