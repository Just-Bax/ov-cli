from __future__ import annotations

import threading
from typing import Any

import httpx
import pytest
from conftest import BASE_URL, seed_session

from ov import credentials
from ov.agent import pagerduty, prompt
from ov.agent.tools import TOOLS_BY_NAME, ToolError, tool_specs

KEY = "u+abcdefghijklmn1234"

SERVICES = [
    {
        "id": "PSVC1",
        "name": "ACME Production",
        "description": "acme.onevizion.test web",
        "escalation_policy": {"id": "PPOL1"},
        "html_url": "https://onevizion.pagerduty.com/service-directory/PSVC1",
    },
    {"id": "PSVC2", "name": "Globex", "description": "", "escalation_policy": {"id": "PPOL2"}},
]


def incident(number: int, status: str, service: str = "PSVC1") -> dict[str, Any]:
    return {
        "id": f"PINC{number}",
        "incident_number": number,
        "title": f"Heap high on acme ({number})",
        "status": status,
        "urgency": "high",
        "service": {"id": service, "summary": "ACME Production"},
        "created_at": "2026-10-04T10:00:00Z",
        "last_status_change_at": "2026-10-04T10:05:00Z",
        "assignments": [{"assignee": {"summary": "Pat"}}],
        "html_url": f"https://onevizion.pagerduty.com/incidents/PINC{number}",
    }


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
            return httpx.Response(
                200,
                json={
                    "user": {
                        "name": "Bax",
                        "email": "b@x.test",
                        "html_url": "https://onevizion.pagerduty.com/users/P1",
                    }
                },
            )
        if path == "/services":
            return httpx.Response(200, json={"services": SERVICES, "more": False})
        if path == "/incidents":
            rows = [
                incident(7, "triggered"),
                incident(6, "resolved"),
                incident(5, "resolved", "PSVC2"),
            ]
            ids = params.get_list("service_ids[]")
            statuses = params.get_list("statuses[]")
            rows = [r for r in rows if (not ids or r["service"]["id"] in ids)]
            rows = [r for r in rows if not statuses or r["status"] in statuses]
            return httpx.Response(200, json={"incidents": rows, "more": False})
        if path == "/incidents/7" or path == "/incidents/PINC7":
            return httpx.Response(200, json={"incident": incident(7, "triggered")})
        if path.endswith("/log_entries"):
            entries = [
                {
                    "type": "acknowledge_log_entry",
                    "created_at": "2026-10-04T10:05:00Z",
                    "summary": "Acknowledged by Pat",
                    "agent": {"summary": "Pat"},
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
            assert params.get_list("escalation_policy_ids[]") in ([], ["PPOL1"])
            rows = [
                {
                    "user": {"summary": "Pat"},
                    "escalation_level": 1,
                    "escalation_policy": {"summary": "ACME"},
                    "schedule": {"summary": "Primary"},
                    "end": "2026-10-05T09:00:00Z",
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


def test_suggestions_and_matches_are_per_host(linked):
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
    found = pagerduty.suggest()
    assert [s["alias"] for s in found["suggestions"]] == ["acme"]
    assert found["suggestions"][0]["services"] == ["PSVC1"]
    pagerduty.save_matches({"acme": ["PSVC1"]})
    assert pagerduty.services_for("acme/mtrac") == ["PSVC1"]


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
    assert "## PagerDuty" in text and "PagerDuty (incidents and on-call)" in text


def test_incident_tools(linked, tmp_path):
    pagerduty.save_matches({"acme": ["PSVC1"]})
    ctx = Ctx(tmp_path)
    out = TOOLS_BY_NAME["pagerduty_incidents"].handler({}, ctx)
    assert "#7 [triggered, high] Heap high on acme (7)" in out and "#5" not in out
    assert linked.requests[-1].url.params.get_list("service_ids[]") == ["PSVC1"]

    open_only = TOOLS_BY_NAME["pagerduty_incidents"].handler({"statuses": ["triggered"]}, ctx)
    assert "#7" in open_only and "#6" not in open_only

    every = TOOLS_BY_NAME["pagerduty_incidents"].handler({"all_services": True}, ctx)
    assert "#5" in every

    detail = TOOLS_BY_NAME["pagerduty_incident"].handler(
        {"incident": "https://onevizion.pagerduty.com/incidents/PINC7"}, ctx
    )
    assert detail.index("trigger:") < detail.index("acknowledge:")
    assert "[Datadog] JVM heap" in detail and "avg:jvm" in detail

    oncall = TOOLS_BY_NAME["pagerduty_oncall"].handler({}, ctx)
    assert "level 1 Pat (ACME, Primary" in oncall and "level 2 Sam" in oncall


def test_an_unmatched_instance_is_explained(linked, tmp_path):
    with pytest.raises(ToolError, match="not matched to a PagerDuty service"):
        TOOLS_BY_NAME["pagerduty_incidents"].handler({}, Ctx(tmp_path))


def test_health_section(linked):
    pagerduty.save_matches({"acme": ["PSVC1"]})
    report = pagerduty.health("acme", 0, 1_791_108_000_000, "24h")
    assert [i["number"] for i in report["open"]] == [7]
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
        saved = httpx.put(f"{base}/api/pagerduty/matches", json={"matches": {"acme": ["PSVC1"]}})
        assert saved.json()["matches"] == {"acme": ["PSVC1"]}
        assert httpx.get(f"{base}/api/pagerduty/services").json()["services"][0]["id"] == "PSVC1"
        bad = httpx.post(f"{base}/api/pagerduty/connect", json={"account": "x", "apiKey": "nope"})
        assert bad.status_code == 400
        assert httpx.delete(f"{base}/api/pagerduty").json()["connected"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
