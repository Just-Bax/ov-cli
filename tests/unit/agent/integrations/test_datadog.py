from __future__ import annotations

import json

import pytest
from helpers.agent import FakeContext
from helpers.fake_datadog import API_KEY, APP_KEY, install_fake_datadog, link_datadog
from helpers.sessions import BASE_URL, seed_session

from ov.agent.engine import prompt
from ov.agent.integrations import datadog
from ov.agent.storage.models import Access
from ov.agent.tools import TOOLS_BY_NAME, tool_specs
from ov.agent.tools.base import ToolError
from ov.core import credentials


@pytest.fixture
def fake(monkeypatch):
    return install_fake_datadog(monkeypatch)


@pytest.fixture
def linked(fake, logged_in):
    return link_datadog(fake)


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


def test_servers_are_grouped_per_instance(linked):
    seed_session("https://dev-acme.onevizion.test")
    found = datadog.discover()
    assert found["groups"] == {
        "acme": "host:(app01.acme-net.example OR web01.acme-net.example OR web02.acme-net.example)",
        "dev-acme": "host:web01.dev-acme-net.example",
    }
    roles = {h["name"]: (h["role"], h["alias"]) for h in found["hosts"]}
    assert roles["web02.acme-net.example"] == ("web", "acme")
    assert roles["acme-net-123.lb.example"][1] is None
    assert roles["db01.other.example"] == ("db", None)


def test_server_groups_become_metric_scopes_and_roles():
    group = datadog.scope_of(["web02.a", "web01.a", "app01.a"])
    assert group == "host:(app01.a OR web01.a OR web02.a)"
    assert datadog.hosts_in(group) == ["app01.a", "web01.a", "web02.a"]
    assert datadog.metric_scope(group) == "host IN (app01.a,web01.a,web02.a)"
    assert datadog.metric_scope("host:web01.a") == "host:web01.a"
    assert datadog.with_role(group, "web") == "host:(web01.a OR web02.a)"
    assert datadog.with_role(group, "all") == group
    with pytest.raises(datadog.DatadogError, match="has: app, web"):
        datadog.with_role(group, "db")
    assert datadog.hosts_in("service:acme env:prod") is None
    assert [datadog.role_of(h) for h in ("web01.a", "acme-app-2", "db-3f9ak.a", "ip-10-0-1")] == [
        "web",
        "acme-app",
        "db",
        "ip",
    ]


def test_a_tenant_uses_its_hosts_match(linked):
    from ov.onevizion import session as session_store
    from ov.onevizion.session import Session

    session_store.save(
        Session(
            base_url=BASE_URL,
            alias="acme/north",
            mode="session",
            bearer_token="T:S",
            expires_at=4102444800.0,
            tenant="North",
            tenant_id="9",
        )
    )
    datadog.save_matches({"acme": "host:acme-app-*"})
    assert datadog.filter_for("acme/north") == "host:acme-app-*"
    datadog.save_matches({"acme": "host:acme-app-*", "acme/north": "service:north"})
    assert datadog.filter_for("acme/north") == "service:north"


def test_tools_are_offered_only_when_connected_and_allowed(fake, logged_in):
    names = {s["function"]["name"] for s in tool_specs()}
    assert not names & set(datadog.AREAS) and "dd_logs" not in names
    assert "Datadog: not connected" in prompt.system_prompt(Access.READ, "")

    fake.denied = {"apm"}
    datadog.connect("datadoghq.com", API_KEY, APP_KEY)
    names = {s["function"]["name"] for s in tool_specs()}
    assert {"dd_logs", "dd_metrics", "dd_monitors", "dd_events"} <= names
    assert "dd_apm" not in names
    assert "- datadog: " in prompt.system_prompt(Access.READ, "")


def test_log_tool_applies_the_instance_filter(linked, tmp_path):
    datadog.save_matches({"acme": "host:acme-app-*"})
    out = TOOLS_BY_NAME["dd_logs"].handler({"query": "status:error"}, Ctx(tmp_path))
    sent = json.loads(linked.requests[-1].content)
    assert sent["filter"]["query"] == "(host:acme-app-*) status:error"
    assert "Deadlock on row 42" in out and "app.datadoghq.com/logs?query=" in out

    grouped = TOOLS_BY_NAME["dd_logs"].handler({"patterns": True}, Ctx(tmp_path))
    assert "2x Deadlock on row <n> in RULE" in grouped


def test_tools_explain_an_unmatched_instance(linked, tmp_path):
    with pytest.raises(ToolError, match="not matched to Datadog"):
        TOOLS_BY_NAME["dd_logs"].handler({}, Ctx(tmp_path))


def test_metric_monitor_event_and_apm_tools(linked, tmp_path):
    datadog.save_matches({"acme": "host:acme-app-* env:prod"})
    ctx = Ctx(tmp_path)

    metric = TOOLS_BY_NAME["dd_metrics"].handler({"query": "avg:jvm.heap_memory"}, ctx)
    assert linked.requests[-1].url.params["query"] == "avg:jvm.heap_memory{host:acme-app-*,env:prod}"
    assert "min 10, avg 20, max 30, latest 30" in metric

    monitors = TOOLS_BY_NAME["dd_monitors"].handler({}, ctx)
    assert "[Alert] Heap high on acme" in monitors
    assert "Other org thing" not in monitors and "Acme disk" not in monitors

    events = TOOLS_BY_NAME["dd_events"].handler({}, ctx)
    assert "Deploy acme" in events

    apm = TOOLS_BY_NAME["dd_apm"].handler({"mode": "slowest"}, ctx)
    assert "p95 2500.0 ms, 40 calls: GET /trackor" in apm


def test_a_denied_scope_names_the_missing_scope(linked, tmp_path):
    datadog.save_matches({"acme": "host:acme*"})
    linked.denied = {"logs"}
    with pytest.raises(ToolError, match="logs_read_data"):
        TOOLS_BY_NAME["dd_logs"].handler({}, Ctx(tmp_path))


def test_times_accept_relative_iso_and_epoch():
    assert datadog.to_ms("1700000000", "now") == 1_700_000_000_000
    assert datadog.to_ms("2026-10-04T10:00:00Z", "now") == 1_791_108_000_000
    assert abs(datadog.to_ms("now-2h", "now") - datadog.to_ms("now", "now") + 7_200_000) < 2000
    with pytest.raises(datadog.DatadogError):
        datadog.to_ms("yesterday", "now")


def test_health_loads_per_section(linked):
    datadog.save_matches({"acme": "host:acme-app-*"})
    meta = datadog.health_meta("acme", "24h")
    assert meta["scope"] == "host:acme-app-*"

    def section(name):
        return datadog.health_section("acme", "24h", name, meta["to"])

    assert [m["name"] for m in section("monitors")["monitors"]][:1] == ["Heap high on acme"]
    assert section("logs")["topErrors"][0]["count"] == 2
    traffic = section("traffic")
    assert traffic["traffic"]["p95Ms"][0]["v"] == 2000.0 and traffic["slowEndpoints"]
    server = section("servers")["servers"][0]
    assert (server["host"], server["role"], server["metrics"]["cpu"]["latest"]) == ("acme-app-01", "acme-app", 30.0)
    assert section("events")["events"]

    before = len(linked.requests)
    section("logs")
    assert len(linked.requests) == before


def test_a_health_section_without_access_is_unavailable(linked):
    datadog.save_matches({})
    meta = datadog.health_meta("acme", "24h")
    with pytest.raises(datadog.Unavailable, match="no Datadog servers"):
        datadog.health_section("acme", "24h", "logs", meta["to"])


def test_long_series_are_averaged_into_buckets():
    points = [{"t": i, "v": float(i % 2)} for i in range(600)]
    out = datadog.downsample(points, 60)
    assert len(out) == 60 and all(p["v"] == 0.5 for p in out)
    assert datadog.downsample(points[:10], 60) == points[:10]


def test_datadog_queries_naming_a_host_skip_the_instance_lookup(logged_in, tmp_path):
    from ov.agent.tools.datadog import _datadog_scope

    assert _datadog_scope({"query": "host:app01.test-lumen-vpc status:error"}, FakeContext(tmp_path)) == ""


ACME_HOSTS = "host:(app01.acme-vpc.example OR web01.acme-vpc.example)"
ACME_ENDPOINT = "acme-vpc.abc123.us-east-1.rds.amazonaws.com"
DATABASE_SCOPES = {
    "oracle.session_count": [
        f"server:{ACME_ENDPOINT},ddagenthostname:app01.acme-vpc.example",
        "server:db01.shared.example,ddagenthostname:web01.acme-vpc.example",
        "server:globex.abc123.us-east-1.rds.amazonaws.com,ddagenthostname:app01.globex.example",
    ],
    "aws.rds.cpuutilization{*}": [
        "dbinstanceidentifier:acme-vpc,engine:oracle-ee",
        "dbinstanceidentifier:acme-archive,engine:oracle-se2",
        "dbinstanceidentifier:acme-north-db,engine:oracle-ee",
        "dbinstanceidentifier:acmecorp,engine:postgres",
        "dbinstanceidentifier:globex,engine:oracle-ee",
    ],
    "aws.rds": ["dbinstanceidentifier:acme-vpc", "dbinstanceidentifier:acme-archive"],
    "oracle.": [f"server:{ACME_ENDPOINT}", "server:db01.shared.example"],
}


@pytest.fixture
def with_databases(linked):
    seed_session("https://acme-north.onevizion.test")
    datadog.save_matches({"acme": ACME_HOSTS})
    linked.metric_scopes = dict(DATABASE_SCOPES)
    datadog.save_databases({"acme": ["acme-archive", "acme-vpc", "db01.shared.example"]})
    return linked


def test_detected_databases_come_from_oracle_agents_and_rds_names(with_databases):
    found = datadog.discover_databases()
    assert found["groups"] == {"acme": ["acme-archive", "acme-vpc", "db01.shared.example"]}
    assert {"acme-vpc", "globex", "db01.shared.example"} <= {d["id"] for d in found["databases"]}


def test_only_matched_databases_are_used(with_databases):
    datadog.save_databases({"acme": []})
    assert datadog.databases_for("acme") == []

    datadog.save_databases({"acme": ["acme-vpc", "db01.shared.example"]})
    assert datadog.databases_for("acme") == [
        {"id": "acme-vpc", "engine": "oracle-ee", "endpoint": ACME_ENDPOINT, "shared": False},
        {"id": "db01.shared.example", "engine": "oracle", "endpoint": "db01.shared.example", "shared": True},
    ]

    before = len(with_databases.requests)
    datadog.databases_for("acme")
    assert len(with_databases.requests) == before


def test_database_section_maps_rds_and_oracle_metrics_back_to_each_database(with_databases):
    meta = datadog.health_meta("acme", "24h")
    rows = {d["id"]: d for d in datadog.health_section("acme", "24h", "database", meta["to"])["databases"]}
    assert set(rows["acme-vpc"]["metrics"]) == {
        "cpu",
        "memory",
        "storage",
        "connections",
        "readLatency",
        "writeLatency",
        "activeSessions",
        "responseTime",
        "sessions",
        "tablespace",
    }
    assert set(rows["db01.shared.example"]["metrics"]) == {
        "cpu",
        "activeSessions",
        "responseTime",
        "sessions",
        "tablespace",
    }
    assert rows["acme-vpc"]["metrics"]["cpu"] == {
        "latest": 30.0,
        "max": 30.0,
        "points": [{"t": 1_700_000_000_000, "v": 10.0}, {"t": 1_700_000_060_000, "v": 30.0}],
    }
    queries = [r.url.params.get("query", "") for r in with_databases.requests]
    assert any("total_storage_space{dbinstanceidentifier IN (acme-archive,acme-vpc)}" in q for q in queries)
    assert not any("dbinstanceidentifier IN" in q and "db01" in q for q in queries)


def test_cpu_comes_from_rds_before_the_oracle_agent(with_databases):
    meta = datadog.health_meta("acme", "24h")
    datadog.health_section("acme", "24h", "database", meta["to"])
    queries = [r.url.params.get("query", "") for r in with_databases.requests]
    assert any("oracle.host_cpu_utilization{server IN (" in q for q in queries)
    assert any("aws.rds.cpuutilization{dbinstanceidentifier IN (acme-archive,acme-vpc)}" in q for q in queries)


def test_picked_databases_are_normalized(with_databases):
    status = datadog.save_databases({"acme": [" DB01.shared.example ", ""]})
    assert status["databases"] == {"acme": ["db01.shared.example"]}


def test_picked_databases_are_forgotten_with_the_instance(with_databases):
    datadog.save_databases({"acme": ["globex"]})
    datadog.forget("acme")
    assert datadog.status()["databases"] == {}


def test_an_instance_without_a_database_says_so(linked):
    datadog.save_matches({"acme": ACME_HOSTS})
    meta = datadog.health_meta("acme", "24h")
    with pytest.raises(datadog.Unavailable, match="No database is matched"):
        datadog.health_section("acme", "24h", "database", meta["to"])


def test_rds_monitors_match_the_instance_by_database_group(with_databases, tmp_path):
    rds = "avg(last_5m):avg:aws.rds.cpuutilization{*} by {dbinstanceidentifier} > 90"
    with_databases.monitors += [
        {
            "id": 4,
            "name": "RDS CPU",
            "overall_state": "Alert",
            "query": rds,
            "state": {"groups": {"dbinstanceidentifier:acme-vpc": {}, "dbinstanceidentifier:globex": {}}},
        },
        {
            "id": 5,
            "name": "RDS CPU old",
            "overall_state": "Alert",
            "query": rds,
            "state": {"groups": {"dbinstanceidentifier:acme-vpc-old": {}}},
        },
    ]
    meta = datadog.health_meta("acme", "24h")
    names = [m["name"] for m in datadog.health_section("acme", "24h", "monitors", meta["to"])["monitors"]]
    assert "RDS CPU" in names and "RDS CPU old" not in names

    out = TOOLS_BY_NAME["dd_monitors"].handler({}, Ctx(tmp_path))
    assert (
        f"databases acme-archive, acme-vpc ({ACME_ENDPOINT}), db01.shared.example (db01.shared.example) [shared]" in out
        and "[Alert] RDS CPU (" in out
    )
