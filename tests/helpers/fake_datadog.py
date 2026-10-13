from __future__ import annotations

import json
from typing import Any

import httpx

from ov.agent.integrations import datadog

from .sessions import BASE_URL, seed_session

API_KEY = "a" * 28 + "1234"
APP_KEY = "b" * 36 + "5678"
AREAS_BY_PATH = {
    "/api/v2/logs/events/search": "logs",
    "/api/v2/logs/analytics/aggregate": "logs",
    "/api/v1/query": "metrics",
    "/api/v1/monitor": "monitors",
    "/api/v2/events": "events",
    "/api/v2/spans/events/search": "apm",
    "/api/v2/spans/analytics/aggregate": "apm",
    "/api/v1/hosts": "hosts",
}


def forbidden() -> httpx.Response:
    return httpx.Response(403, json={"errors": ["Forbidden"]})


class FakeDatadog:
    def __init__(self) -> None:
        self.denied: set[str] = set()
        self.requests: list[httpx.Request] = []
        self.logs = [
            {"host": "acme-app-01", "service": "tomcat", "message": "Deadlock on row 42 in RULE"},
            {"host": "acme-app-02", "service": "tomcat", "message": "Deadlock on row 77 in RULE"},
            {"host": "acme-app-01", "service": "tomcat", "message": "Import 9 failed: 'x.csv'"},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.headers.get("DD-API-KEY") != API_KEY:
            return forbidden()
        if path == "/api/v1/validate":
            return httpx.Response(200, json={"valid": True})
        if request.headers.get("DD-APPLICATION-KEY") != APP_KEY or AREAS_BY_PATH.get(path) in self.denied:
            return forbidden()

        routes = {
            "/api/v2/logs/events/search": lambda: {"data": [self._log(row) for row in self.logs]},
            "/api/v2/logs/analytics/aggregate": lambda: self._aggregate(json.loads(request.content)),
            "/api/v1/query": lambda: self._query(request.url.params["query"]),
            "/api/v1/hosts": self._hosts,
            "/api/v1/monitor": self._monitors,
            "/api/v2/events": self._events,
            "/api/v2/spans/analytics/aggregate": lambda: self._spans(request.content.decode()),
        }
        route = routes.get(path)
        return httpx.Response(200, json=route() if route else {"data": []})

    @staticmethod
    def _query(query: str) -> dict[str, Any]:
        series = {
            "expression": query,
            "scope": "host:acme-app-01",
            "pointlist": [[1_700_000_000_000, 10.0], [1_700_000_060_000, 30.0]],
        }
        return {"series": [series]}

    @staticmethod
    def _hosts() -> dict[str, Any]:
        names = [
            "web01.acme-net.example",
            "web02.acme-net.example",
            "app01.acme-net.example",
            "web01.dev-acme-net.example",
            "acme-net-123.lb.example",
            "db01.other.example",
        ]
        return {"host_list": [{"name": n} for n in names], "total_matching": len(names)}

    @staticmethod
    def _events() -> dict[str, Any]:
        event = {
            "timestamp": "2026-10-04T10:00:00Z",
            "message": "Deployed 26.4",
            "attributes": {"title": "Deploy acme", "source_type_name": "ci"},
        }
        return {"data": [{"attributes": event}]}

    @staticmethod
    def _spans(body: str) -> dict[str, Any]:
        if "@span.kind:server" in body:
            points = [{"time": "2026-10-04T10:00:00Z", "value": 2_000_000_000}]
            return {"data": [{"attributes": {"compute": {"c0": points, "c1": points}}}]}
        bucket = {"by": {"resource_name": "GET /trackor"}, "compute": {"c0": 2_500_000_000, "c1": 40}}
        return {"data": [{"type": "bucket", "attributes": bucket}]}

    @staticmethod
    def _log(row: dict[str, str]) -> dict[str, Any]:
        return {
            "attributes": {
                "timestamp": "2026-10-04T10:00:00Z",
                "status": "error",
                "attributes": {},
                **row,
            }
        }

    def _aggregate(self, body: dict[str, Any]) -> dict[str, Any]:
        group = (body.get("group_by") or [{}])[0].get("facet")
        compute = body["compute"][0]
        if compute.get("type") == "timeseries":
            points = [{"time": "2026-10-04T10:00:00Z", "value": 5}]
            return {"data": {"buckets": [{"computes": {"c0": points}}]}}
        if group:
            counts: dict[str, int] = {}
            for row in self.logs:
                counts[row[group]] = counts.get(row[group], 0) + 100
            return {"data": {"buckets": [{"by": {group: k}, "computes": {"c0": v}} for k, v in counts.items()]}}
        return {"data": {"buckets": [{"computes": {"c0": 300}}]}}

    @staticmethod
    def _monitors() -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "name": "Heap high on acme",
                "overall_state": "Alert",
                "query": "avg:jvm.heap_memory{host:acme-app-01}",
                "state": {"groups": {"host:acme-app-01": {}}},
            },
            {"id": 2, "name": "Other org thing", "overall_state": "Alert", "query": "x{host:zz}"},
            {"id": 3, "name": "Acme disk", "overall_state": "OK", "query": "y{host:acme-app-02}"},
        ]


def install_fake_datadog(monkeypatch) -> FakeDatadog:
    dd = FakeDatadog()
    monkeypatch.setattr(datadog, "TRANSPORT", httpx.MockTransport(dd.handler))
    datadog._health_cache.clear()
    return dd


def link_datadog(fake: FakeDatadog) -> FakeDatadog:
    seed_session(BASE_URL)
    datadog.connect("https://app.datadoghq.com/logs", API_KEY, APP_KEY)
    return fake
