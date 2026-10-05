from __future__ import annotations

import threading
from typing import Any

import httpx
import pytest
from conftest import BASE_URL, seed_session

from ov import credentials
from ov.agent import pagerduty, prompt
from ov.agent.tools import TOOLS_BY_NAME, tool_specs

KEY = "u+abcdefghijklmn1234"
HOST = "acme.onevizion.test"


def incident(number: int, status: str, title: str, details: dict | str | None, policy: str = "PPOL1") -> dict[str, Any]:
    return {
        "id": f"PINC{number}",
        "incident_number": number,
        "title": title,
        "status": status,
        "urgency": "high",
        "service": {"id": "PSVC1", "summary": "Monitoring High & Critical"},
        "escalation_policy": {"id": policy},
        "created_at": "2026-10-04T10:00:00Z",
        "last_status_change_at": "2026-10-04T10:05:00Z",
        "assignments": [{"assignee": {"summary": "Pat"}}],
        "html_url": f"https://onevizion.pagerduty.com/incidents/PINC{number}",
        "first_trigger_log_entry": {"channel": {"type": "api", "details": details}},
    }


INCIDENTS = [
    # OV monitoring website alert: website and database together.
    incident(7, "triggered", "Unhealthy Hosts", {"website": HOST, "database": "acmedb"}),
    # Database alert for the same database: no website.
    incident(6, "resolved", "High CPU", {"website": "none", "database": "acmedb"}),
    # Datadog alert naming the host in its title.
    incident(5, "acknowledged", f"[Synthetics] Latency for {HOST}", {"body": "slow"}, "PPOL2"),
    # Another customer.
    incident(4, "resolved", "Unhealthy Hosts", {"website": "globex.onevizion.test"}),
    # A Datadog alert with a tag naming the instance's first label.
    incident(3, "resolved", "[AWS] RDS CPU high on dbinstanceidentifier:acme", "x"),
]


class FakePagerDuty:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.denied: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("Authorization") != f"Token token={KEY}":
            return httpx.Response(401, json={"error": {"message": "Unauthorized"}})
        path = request.url.path
        area = {"/incidents": "incidents", "/services": "services", "/oncalls": "oncall"}.get(path)
        if area in self.denied:
            return httpx.Response(403, json={"error": {"message": "Forbidden"}})
        params = request.url.params
        if path == "/users/me":
            user = {"name": "Bax", "html_url": "https://onevizion.pagerduty.com/users/P1"}
            return httpx.Response(200, json={"user": user})
        if path == "/services":
            return httpx.Response(200, json={"services": [], "more": False})
        if path == "/incidents":
            if params.get("limit") != "1":
                assert params.get_list("include[]") == ["first_trigger_log_entries"]
            statuses = params.get_list("statuses[]")
            rows = [r for r in INCIDENTS if not statuses or r["status"] in statuses]
            return httpx.Response(200, json={"incidents": rows, "more": False})
        if path == "/incidents/PINC7":
            return httpx.Response(200, json={"incident": INCIDENTS[0]})
        if path.endswith("/log_entries"):
            entries = [
                {
                    "type": "acknowledge_log_entry",
                    "created_at": "2026-10-04T10:05:00Z",
                    "summary": "Acknowledged by Pat",
                },
                {
                    "type": "trigger_log_entry",
                    "created_at": "2026-10-04T10:00:00Z",
                    "summary": "Triggered through the API",
                },
            ]
            return httpx.Response(200, json={"log_entries": entries})
        if path.endswith("/alerts"):
            alert = {
                "created_at": "2026-10-04T10:00:00Z",
                "status": "triggered",
                "summary": "[Datadog] JVM heap",
                "body": {"details": {"query": "avg:jvm"}},
            }
            return httpx.Response(200, json={"alerts": [alert]})
        if path.endswith("/notes"):
            return httpx.Response(200, json={"notes": []})
        if path == "/oncalls":
            policies = params.get_list("escalation_policy_ids[]")
            rows = [
                {
                    "user": {"summary": "Pat"},
                    "escalation_level": 1,
                    "escalation_policy": {"summary": f"policies {','.join(policies) or 'all'}"},
                    "schedule": {"summary": "Primary"},
                },
                {
                    "user": {"summary": "Sam"},
                    "escalation_level": 2,
                    "escalation_policy": {"summary": "ACME"},
                },
            ]
            return httpx.Response(200, json={"oncalls": rows, "more": False})
        return httpx.Response(404, json={"error": {"message": "Not found"}})


@pytest.fixture
def fake(monkeypatch):
    pd = FakePagerDuty()
    monkeypatch.setattr(pagerduty, "TRANSPORT", httpx.MockTransport(pd.handler))
    pagerduty._forget_caches()
    return pd


@pytest.fixture
def linked(fake, logged_in):
    seed_session(BASE_URL)
    pagerduty.connect("https://onevizion.pagerduty.com/incidents?status=triggered", KEY)
    return fake


class Ctx:
    def __init__(self, tmp_path, instance: str = "acme") -> None:
        self.work_dir = tmp_path
        self.instance = instance


def test_account_and_region_come_from_any_pagerduty_address():
    assert pagerduty.account_of("https://onevizion.pagerduty.com/incidents") == ("onevizion", "us")
    assert pagerduty.account_of("acme.eu.pagerduty.com") == ("acme", "eu")
    assert pagerduty.account_of("onevizion") == ("onevizion", "us")
    with pytest.raises(pagerduty.PagerDutyError):
        pagerduty.account_of("https://example.com/x")


def test_connect_checks_the_key_and_keeps_it_in_the_keyring(fake, ov_home):
    fake.denied = {"oncall"}
    status = pagerduty.connect("onevizion.pagerduty.com", f" {KEY} ")
    assert status["connected"] and status["user"] == "Bax" and status["keyLast4"] == "1234"
    assert status["permissions"] == {"incidents": True, "services": True, "oncall": False}
    assert status["webUrl"] == "https://onevizion.pagerduty.com"
    assert credentials.get(pagerduty.CREDENTIAL_KEY) == {"api_key": KEY}
    assert KEY not in (ov_home / "agent" / "pagerduty.json").read_text(encoding="utf-8")
    assert all(r.url.host == "api.pagerduty.com" for r in fake.requests)


def test_a_bad_key_is_explained_and_not_stored(fake, ov_home):
    with pytest.raises(pagerduty.PagerDutyError, match="User API token"):
        pagerduty.connect("onevizion", "wrong")
    assert credentials.get(pagerduty.CREDENTIAL_KEY) is None and not pagerduty.connected()


def test_incidents_are_tied_to_instances_by_website_database_and_host(linked):
    rows = pagerduty.incidents(0, 1_791_108_000_000)
    mine = pagerduty.for_instance(rows, "acme")
    assert [r["number"] for r in mine] == [7, 6, 5, 3]
    # The database seen on a website alert is remembered for later database-only alerts.
    assert pagerduty.load_state()["databases"] == {HOST: ["acmedb"]}
    assert [r["number"] for r in pagerduty.for_instance(rows[1:2], "acme")] == [6]


def test_a_tenant_sees_its_host_incidents(linked):
    from ov import session as session_store
    from ov.session import Session

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
    rows = pagerduty.incidents(0, 1_791_108_000_000)
    assert len(pagerduty.for_instance(rows, "acme/north")) == 4


def test_website_map_lists_signed_in_instances_first(linked):
    found = pagerduty.website_map(7)
    assert found["total"] == 5 and found["matched"] == 4
    first, second = found["websites"][:2]
    assert (first["host"], first["alias"], first["count"], first["open"]) == (HOST, "acme", 4, 2)
    assert (second["host"], second["alias"], second["count"]) == ("globex.onevizion.test", None, 1)


def test_tools_are_offered_only_when_connected(fake, logged_in):
    names = {s["function"]["name"] for s in tool_specs()}
    assert not {n for n in names if n.startswith("pagerduty_")}
    assert "PagerDuty: not connected" in prompt.system_prompt(False, "")

    fake.denied = {"oncall"}
    pagerduty.connect("onevizion", KEY)
    names = {s["function"]["name"] for s in tool_specs()}
    assert {"pagerduty_incidents", "pagerduty_incident"} <= names
    assert "pagerduty_oncall" not in names
    text = prompt.system_prompt(False, "")
    assert "- pagerduty: " in text and "PagerDuty (incidents and on-call)" in text


def test_incident_tools(linked, tmp_path):
    ctx = Ctx(tmp_path)
    out = TOOLS_BY_NAME["pagerduty_incidents"].handler({}, ctx)
    assert f"for {HOST}" in out and "#7 [triggered, high] Unhealthy Hosts" in out and "#4" not in out

    open_only = TOOLS_BY_NAME["pagerduty_incidents"].handler({"statuses": ["triggered"]}, ctx)
    assert "#7" in open_only and "#6" not in open_only
    every = TOOLS_BY_NAME["pagerduty_incidents"].handler({"all_instances": True}, ctx)
    assert "#4" in every
    found = TOOLS_BY_NAME["pagerduty_incidents"].handler({"query": "acmedb"}, ctx)
    assert "#7" in found and "#5" not in found

    detail = TOOLS_BY_NAME["pagerduty_incident"].handler(
        {"incident": "https://onevizion.pagerduty.com/incidents/PINC7"}, ctx
    )
    assert detail.index("trigger:") < detail.index("acknowledge:")
    assert "[Datadog] JVM heap" in detail and "avg:jvm" in detail

    oncall = TOOLS_BY_NAME["pagerduty_oncall"].handler({}, ctx)
    assert "level 1 Pat (policies PPOL1,PPOL2, Primary" in oncall and "level 2 Sam" in oncall
    everyone = TOOLS_BY_NAME["pagerduty_oncall"].handler({}, Ctx(tmp_path, instance=""))
    assert "policies all" in everyone


def test_health_section(linked):
    report = pagerduty.health("acme", 0, 1_791_108_000_000, "24h")
    assert [i["number"] for i in report["open"]] == [7, 5]
    assert [i["number"] for i in report["incidents"]] == [7, 6, 5, 3]
    assert "text" not in report["open"][0]
    assert [o["user"] for o in report["oncall"]] == ["Pat"]
    assert not report["errors"]


def test_the_api_never_returns_the_key(linked):
    from ov.agent.server import AgentServer, Handler

    httpd = AgentServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status = httpx.get(f"{base}/api/pagerduty")
        assert status.json()["connected"] and KEY not in status.text
        sites = httpx.get(f"{base}/api/pagerduty/websites", params={"days": 7}).json()
        assert sites["websites"][0]["host"] == HOST
        bad = httpx.post(f"{base}/api/pagerduty/connect", json={"account": "x", "apiKey": "nope"})
        assert bad.status_code == 400
        assert httpx.delete(f"{base}/api/pagerduty").json()["connected"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
