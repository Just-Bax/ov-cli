from __future__ import annotations

import json
from typing import Any

import httpx

from ov.agent.integrations import pagerduty

from .sessions import BASE_URL, seed_session

KEY = "u+abcdefghijklmn1234"
HOST = "acme.onevizion.test"
AREAS_BY_PATH = {"/incidents": "incidents", "/oncalls": "oncall"}


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
    incident(7, "triggered", "Unhealthy Hosts", {"website": HOST, "database": "acmedb"}),
    incident(6, "resolved", "High CPU", {"website": "none", "database": "acmedb"}),
    incident(5, "acknowledged", f"[Synthetics] Latency for {HOST}", {"body": "slow"}, "PPOL2"),
    incident(4, "resolved", "Unhealthy Hosts", {"website": "globex.onevizion.test"}),
    incident(3, "resolved", "[AWS] RDS CPU high on dbinstanceidentifier:acme", "x"),
]


class FakePagerDuty:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.denied: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.headers.get("Authorization") != f"Token token={KEY}":
            return httpx.Response(401, json={"error": {"message": "Unauthorized"}})
        if AREAS_BY_PATH.get(path) in self.denied:
            return httpx.Response(403, json={"error": {"message": "Forbidden"}})

        params = request.url.params
        if request.method != "GET":
            return self._write(request)

        routes = {
            "/users/me": lambda: {
                "user": {
                    "name": "Bax",
                    "email": "bax@example.test",
                    "html_url": "https://onevizion.pagerduty.com/users/P1",
                }
            },
            "/incidents": lambda: self._incidents(params),
            "/incidents/PINC7": lambda: {"incident": INCIDENTS[0]},
            "/incidents/PINC7/log_entries": self._log_entries,
            "/incidents/PINC7/alerts": self._alerts,
            "/incidents/PINC7/notes": lambda: {"notes": []},
            "/oncalls": lambda: self._oncalls(params.get_list("escalation_policy_ids[]")),
            "/escalation_policies": lambda: {
                "escalation_policies": [{"id": "PUSA1", "name": "USA Support"}, {"id": "PEU01", "name": "EU Support"}],
                "more": False,
            },
            "/users": lambda: {
                "users": [{"id": "PUSR1", "name": "Pat Lee", "email": "pat@example.test"}],
                "more": False,
            },
        }
        route = routes.get(path)
        if route is None:
            return httpx.Response(404, json={"error": {"message": "Not found"}})
        return httpx.Response(200, json=route())

    def _write(self, request: httpx.Request) -> httpx.Response:
        if "read-only" in self.denied:
            return httpx.Response(403, json={"error": {"message": "Access Denied"}})
        assert request.headers["From"] == "bax@example.test"

        if request.url.path == "/incidents/PINC7":
            changed = json.loads(request.content)["incident"]
            return httpx.Response(
                200, json={"incident": {**INCIDENTS[0], "status": changed.get("status", "triggered")}}
            )

        return httpx.Response(201, json={})

    @staticmethod
    def _incidents(params: httpx.QueryParams) -> dict[str, Any]:
        if params.get("limit") != "1":
            assert params.get_list("include[]") == ["first_trigger_log_entries"]
        statuses = params.get_list("statuses[]")
        rows = [r for r in INCIDENTS if not statuses or r["status"] in statuses]
        return {"incidents": rows, "more": False}

    @staticmethod
    def _log_entries() -> dict[str, Any]:
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
        return {"log_entries": entries}

    @staticmethod
    def _alerts() -> dict[str, Any]:
        alert = {
            "created_at": "2026-10-04T10:00:00Z",
            "status": "triggered",
            "summary": "[Datadog] JVM heap",
            "body": {"details": {"query": "avg:jvm"}},
        }
        return {"alerts": [alert]}

    @staticmethod
    def _oncalls(policies: list[str]) -> dict[str, Any]:
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
        return {"oncalls": rows, "more": False}


def install_fake_pagerduty(monkeypatch) -> FakePagerDuty:
    pd = FakePagerDuty()
    monkeypatch.setattr(pagerduty, "TRANSPORT", httpx.MockTransport(pd.handler))
    pagerduty._health_cache.clear()
    return pd


def link_pagerduty(fake: FakePagerDuty) -> FakePagerDuty:
    seed_session(BASE_URL)
    pagerduty.connect("https://onevizion.pagerduty.com/incidents?status=triggered", KEY)
    return fake
