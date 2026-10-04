from __future__ import annotations

import json
import threading
from typing import Any

import httpx
import pytest
from conftest import BASE_URL, seed_session

from ov import credentials
from ov.agent import datadog, prompt
from ov.agent.tools import TOOLS_BY_NAME, ToolError, tool_specs

API_KEY = "a" * 28 + "1234"
APP_KEY = "b" * 36 + "5678"


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
        if request.headers.get("DD-API-KEY") != API_KEY:
            return httpx.Response(403, json={"errors": ["Forbidden"]})
        path = request.url.path
        if path == "/api/v1/validate":
            return httpx.Response(200, json={"valid": True})
        if request.headers.get("DD-APPLICATION-KEY") != APP_KEY:
            return httpx.Response(403, json={"errors": ["Forbidden"]})
        area = {
            "/api/v2/logs/events/search": "logs",
            "/api/v2/logs/analytics/aggregate": "logs",
            "/api/v1/query": "metrics",
            "/api/v1/monitor": "monitors",
            "/api/v2/events": "events",
            "/api/v2/spans/events/search": "apm",
            "/api/v2/spans/analytics/aggregate": "apm",
            "/api/v1/hosts": "hosts",
        }.get(path)
        if area in self.denied:
            return httpx.Response(403, json={"errors": ["Forbidden"]})
        body = json.loads(request.content) if request.content else {}
        if path == "/api/v2/logs/events/search":
            return httpx.Response(200, json={"data": [self._log(row) for row in self.logs]})
        if path == "/api/v2/logs/analytics/aggregate":
            return httpx.Response(200, json=self._aggregate(body))
        if path == "/api/v1/query":
            return httpx.Response(
                200,
                json={
                    "series": [
                        {
                            "expression": request.url.params["query"],
                            "scope": "host:acme-app-01",
                            "pointlist": [[1_700_000_000_000, 10.0], [1_700_000_060_000, 30.0]],
                        }
                    ]
                },
            )
        if path == "/api/v1/monitor":
            return httpx.Response(200, json=self._monitors())
        if path == "/api/v2/events":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "attributes": {
                                "timestamp": "2026-10-04T10:00:00Z",
                                "message": "Deployed 26.4",
                                "attributes": {"title": "Deploy acme", "source_type_name": "ci"},
                            }
                        }
                    ]
                },
            )
        if (
            path == "/api/v2/spans/analytics/aggregate"
            and "@span.kind:server" in request.content.decode()
        ):
            points = [{"time": "2026-10-04T10:00:00Z", "value": 2_000_000_000}]
            return httpx.Response(
                200,
                json={"data": [{"attributes": {"compute": {"c0": points, "c1": points}}}]},
            )
        if path == "/api/v2/spans/analytics/aggregate":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "type": "bucket",
                            "attributes": {
                                "by": {"resource_name": "GET /trackor"},
                                "compute": {"c0": 2_500_000_000, "c1": 40},
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"data": []})

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
            return {
                "data": {
                    "buckets": [
                        {"by": {group: k}, "computes": {"c0": v}} for k, v in counts.items()
                    ]
                }
            }
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


@pytest.fixture
def fake(monkeypatch):
    dd = FakeDatadog()
    monkeypatch.setattr(datadog, "TRANSPORT", httpx.MockTransport(dd.handler))
    datadog._health_cache.clear()
    return dd


@pytest.fixture
def linked(fake, logged_in):
    seed_session(BASE_URL)
    datadog.connect("https://app.datadoghq.com/logs", API_KEY, APP_KEY)
    return fake


class Ctx:
    def __init__(self, tmp_path, instance: str = "acme") -> None:
        self.work_dir = tmp_path
        self.instance = instance


def test_site_is_read_from_any_datadog_url():
    assert datadog.site_of("https://app.datadoghq.com/personal-settings/x") == "datadoghq.com"
    assert datadog.site_of("us5.datadoghq.com") == "us5.datadoghq.com"
    assert datadog.site_of("https://app.datadoghq.eu") == "datadoghq.eu"
    assert datadog.site_of("") == "datadoghq.com"
    with pytest.raises(datadog.DatadogError):
        datadog.site_of("example.com")


def test_connect_checks_both_keys_and_reports_what_it_can_read(fake, ov_home):
    fake.denied = {"apm", "hosts"}
    status = datadog.connect("datadoghq.com", f" {API_KEY} ", APP_KEY)
    assert status["connected"] and status["apiKeyLast4"] == "1234"
    assert status["permissions"] == {
        "logs": True,
        "metrics": True,
        "monitors": True,
        "events": True,
        "apm": False,
        "hosts": False,
    }
    assert credentials.get(datadog.CREDENTIAL_KEY) == {"api_key": API_KEY, "app_key": APP_KEY}
    # Secrets stay in the credential store, never in the plain state file.
    assert API_KEY not in (ov_home / "agent" / "datadog.json").read_text(encoding="utf-8")
    assert all(r.url.host == "api.datadoghq.com" for r in fake.requests)


def test_bad_keys_are_explained_and_not_stored(fake, ov_home):
    with pytest.raises(datadog.DatadogError, match="API key"):
        datadog.connect("datadoghq.com", "wrong", APP_KEY)
    with pytest.raises(datadog.DatadogError, match="application key cannot read"):
        datadog.connect("datadoghq.com", API_KEY, "wrong")
    assert credentials.get(datadog.CREDENTIAL_KEY) is None
    assert not datadog.connected()


def test_disconnect_forgets_the_keys_but_keeps_matches(linked):
    datadog.save_matches({"acme": "host:acme-app-*"})
    status = datadog.disconnect()
    assert not status["connected"] and status["matches"] == {"acme": "host:acme-app-*"}
    assert credentials.get(datadog.CREDENTIAL_KEY) is None


def test_discovery_suggests_a_host_wildcard_for_the_instance(linked):
    found = datadog.discover()
    acme = next(s for s in found["suggestions"] if s["alias"] == "acme")
    assert acme["filter"] == "host:acme-app-0*"
    assert {v["value"] for v in found["values"]} >= {"acme-app-01", "tomcat"}


def test_a_tenant_uses_its_hosts_match(linked):
    from ov import session as session_store
    from ov.session import Session

    session_store.save(
        Session(
            base_url=BASE_URL,
            alias="acme/mtrac",
            mode="session",
            bearer_token="T:S",
            expires_at=4102444800.0,
            tenant="mTRAC",
            tenant_id="9",
        )
    )
    datadog.save_matches({"acme": "host:acme-app-*"})
    assert datadog.filter_for("acme/mtrac") == "host:acme-app-*"
    datadog.save_matches({"acme": "host:acme-app-*", "acme/mtrac": "service:mtrac"})
    assert datadog.filter_for("acme/mtrac") == "service:mtrac"


def test_tools_are_offered_only_when_connected_and_allowed(fake, logged_in):
    names = {s["function"]["name"] for s in tool_specs()}
    assert not names & set(datadog.AREAS) and "datadog_logs" not in names
    assert "Datadog: not connected" in prompt.system_prompt(False, "")

    fake.denied = {"apm"}
    datadog.connect("datadoghq.com", API_KEY, APP_KEY)
    names = {s["function"]["name"] for s in tool_specs()}
    assert {"datadog_logs", "datadog_metrics", "datadog_monitors", "datadog_events"} <= names
    assert "datadog_apm" not in names
    assert "## Datadog" in prompt.system_prompt(False, "")


def test_log_tool_applies_the_instance_filter(linked, tmp_path):
    datadog.save_matches({"acme": "host:acme-app-*"})
    out = TOOLS_BY_NAME["datadog_logs"].handler({"query": "status:error"}, Ctx(tmp_path))
    sent = json.loads(linked.requests[-1].content)
    assert sent["filter"]["query"] == "(host:acme-app-*) status:error"
    assert "Deadlock on row 42" in out and "app.datadoghq.com/logs?query=" in out

    grouped = TOOLS_BY_NAME["datadog_logs"].handler({"patterns": True}, Ctx(tmp_path))
    assert "2x Deadlock on row <n> in RULE" in grouped


def test_tools_explain_an_unmatched_instance(linked, tmp_path):
    with pytest.raises(ToolError, match="not matched to Datadog"):
        TOOLS_BY_NAME["datadog_logs"].handler({}, Ctx(tmp_path))


def test_metric_monitor_event_and_apm_tools(linked, tmp_path):
    datadog.save_matches({"acme": "host:acme-app-* env:prod"})
    ctx = Ctx(tmp_path)

    metric = TOOLS_BY_NAME["datadog_metrics"].handler({"query": "avg:jvm.heap_memory"}, ctx)
    assert (
        linked.requests[-1].url.params["query"] == "avg:jvm.heap_memory{host:acme-app-*,env:prod}"
    )
    assert "min 10, avg 20, max 30, latest 30" in metric

    monitors = TOOLS_BY_NAME["datadog_monitors"].handler({}, ctx)
    assert "[Alert] Heap high on acme" in monitors
    assert "Other org thing" not in monitors and "Acme disk" not in monitors

    events = TOOLS_BY_NAME["datadog_events"].handler({}, ctx)
    assert "Deploy acme" in events

    apm = TOOLS_BY_NAME["datadog_apm"].handler({"mode": "slowest"}, ctx)
    assert "p95 2500.0 ms, 40 calls: GET /trackor" in apm


def test_a_denied_scope_names_the_missing_scope(linked, tmp_path):
    datadog.save_matches({"acme": "host:acme*"})
    linked.denied = {"logs"}
    with pytest.raises(ToolError, match="logs_read_data"):
        TOOLS_BY_NAME["datadog_logs"].handler({}, Ctx(tmp_path))


def test_times_accept_relative_iso_and_epoch():
    assert datadog.to_ms("1700000000", "now") == 1_700_000_000_000
    assert datadog.to_ms("2026-10-04T10:00:00Z", "now") == 1_791_108_000_000
    assert abs(datadog.to_ms("now-2h", "now") - datadog.to_ms("now", "now") + 7_200_000) < 2000
    with pytest.raises(datadog.DatadogError):
        datadog.to_ms("yesterday", "now")


def test_health_report(linked):
    datadog.save_matches({"acme": "host:acme-app-*"})
    report = datadog.health("acme", "24h", lambda: [{"type": "Import", "count": 2}])
    assert report["scope"] == "host:acme-app-*"
    assert [m["name"] for m in report["monitors"]][:1] == ["Heap high on acme"]
    assert report["topErrors"][0]["count"] == 2
    assert report["onevizion"] == [{"type": "Import", "count": 2}]
    assert {m["title"] for m in report["metrics"]} >= {"CPU", "JVM heap"}
    assert "slowEndpoints" in report and not report["errors"]
    assert report["traffic"]["p95Ms"][0]["v"] == 2000.0

    # Cached: a second call makes no requests.
    before = len(linked.requests)
    datadog.health("acme", "24h")
    assert len(linked.requests) == before


def test_long_series_are_averaged_into_buckets():
    points = [{"t": i, "v": float(i % 2)} for i in range(600)]
    out = datadog.downsample(points, 60)
    assert len(out) == 60 and all(p["v"] == 0.5 for p in out)
    assert datadog.downsample(points[:10], 60) == points[:10]


def test_the_api_never_returns_keys(linked):
    from ov.agent.server import AgentServer, Handler

    httpd = AgentServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status = httpx.get(f"{base}/api/datadog")
        assert status.status_code == 200 and status.json()["connected"]
        assert API_KEY not in status.text and APP_KEY not in status.text

        bad = httpx.post(f"{base}/api/datadog/connect", json={"apiKey": "x", "appKey": "y"})
        assert bad.status_code == 400

        saved = httpx.put(f"{base}/api/datadog/matches", json={"matches": {"acme": "host:a*"}})
        assert saved.json()["matches"] == {"acme": "host:a*"}
        health = httpx.get(f"{base}/api/instance-health", params={"instance": "acme"})
        assert health.status_code == 200 and health.json()["scope"] == "host:a*"
        assert httpx.delete(f"{base}/api/datadog").json()["connected"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
