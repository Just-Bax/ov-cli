from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from helpers.sessions import seed_session

from ov.agent.instances import maintenance
from ov.agent.instances.maintenance import MaintenanceUnavailable, maintenance_for

END = int(datetime(2026, 11, 5, tzinfo=UTC).timestamp() * 1000)
HOSTS = ["app01.acme-vpc.internal.example", "web01.acme-vpc.internal.example"]


def row(key, website, server, status="Completed", start="2026-11-02T01:30:00", **extra):
    return {
        "TRACKOR_ID": 100,
        "TRACKOR_KEY": key,
        "MNT_TYPE": "General Deployment",
        "MNT_STATUS": status,
        "MNT_MAINTENANCE_START": start,
        "MNT_MAINTENANCE_END": None,
        "MNT_DURATION": "30",
        "MNT_VERSION_TO_DEPLOY": "26.20.0",
        "MNT_OWNER": "jdoe (Jane Doe)",
        "Website.TRACKOR_KEY": website,
        "Server.TRACKOR_KEY": server,
        **extra,
    }


ROWS = [
    row("DEPL-1", "acme.onevizion.test", "app01.acme-vpc"),
    row("DEPL-1", "acme.onevizion.test", "web01.acme-vpc"),
    row("DEPL-2", "dev-acme.onevizion.test", "app01.dev-acme-vpc"),
    row("REBOOT-3", None, "web01.acme-vpc", status="Scheduled", start=None),
    row("OLD-4", "acme.onevizion.test", "app01.acme-vpc", status="Ready for Review", start="2026-06-01T00:00:00"),
]


class FakeClient:
    def __init__(self) -> None:
        self.queries = []

    def api(self, method, path, params):
        self.queries.append(dict(params))
        return self

    def json(self):
        return ROWS


@pytest.fixture
def client(ov_home, monkeypatch):
    seed_session("https://acme.onevizion.test")
    seed_session("https://trackor.onevizion.com")
    fake = FakeClient()

    @contextmanager
    def opened(_alias):
        yield fake

    monkeypatch.setattr(maintenance, "open_client", opened)
    return fake


def test_maintenance_is_the_instances_own_work_in_utc(client):
    items = {i["key"]: i for i in maintenance_for("acme", HOSTS, END)["items"]}
    assert set(items) == {"DEPL-1", "REBOOT-3"}

    deploy = items["DEPL-1"]
    assert deploy["servers"] == ["app01.acme-vpc", "web01.acme-vpc"] and deploy["owner"] == "Jane Doe"
    assert deploy["start"] == int(datetime(2026, 11, 2, 6, 30, tzinfo=UTC).timestamp() * 1000)
    assert {q["Website.TRACKOR_KEY"] for q in client.queries if "Website.TRACKOR_KEY" in q} == {"acme.onevizion.test"}
    assert {q["Server.TRACKOR_KEY"] for q in client.queries if "Server.TRACKOR_KEY" in q} == {"acme-vpc"}


def test_maintenance_needs_oneteam_signed_in(ov_home):
    seed_session("https://acme.onevizion.test")
    with pytest.raises(MaintenanceUnavailable, match="OneTeam"):
        maintenance_for("acme", HOSTS, END)
