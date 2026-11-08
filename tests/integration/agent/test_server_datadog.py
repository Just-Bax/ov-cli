from __future__ import annotations

import httpx
import pytest
from helpers.fake_datadog import API_KEY, APP_KEY, install_fake_datadog, link_datadog


@pytest.fixture
def linked(monkeypatch, logged_in):
    return link_datadog(install_fake_datadog(monkeypatch))


def test_the_api_never_returns_keys(linked, agent_server):
    base = agent_server

    status = httpx.get(f"{base}/api/datadog")
    assert status.status_code == 200 and status.json()["connected"]
    assert API_KEY not in status.text and APP_KEY not in status.text

    bad = httpx.post(f"{base}/api/datadog/connect", json={"apiKey": "x", "appKey": "y"})
    assert bad.status_code == 400

    saved = httpx.put(f"{base}/api/datadog/matches", json={"matches": {"acme": "host:a*"}})
    assert saved.json()["matches"] == {"acme": "host:a*"}

    meta = httpx.get(f"{base}/api/instance-health/meta", params={"instance": "acme"}).json()
    assert meta["scope"] == "host:a*"
    params = {"instance": "acme", "to": meta["to"]}

    maintenance = httpx.get(f"{base}/api/instance-health/maintenance", params=params).json()
    assert maintenance == {"unavailable": "Sign in to trackor.onevizion.com to see maintenance from OneTeam."}
    missing = httpx.get(f"{base}/api/instance-health/incidents", params=params).json()
    assert missing == {"unavailable": "PagerDuty is not connected."}

    assert httpx.delete(f"{base}/api/datadog").json()["connected"] is False


def test_databases_can_be_listed_and_picked(linked, agent_server):
    base = agent_server

    assert "databases" in httpx.get(f"{base}/api/datadog/databases").json()
    picked = httpx.put(f"{base}/api/datadog/databases", json={"databases": {"acme": ["shared01"]}})
    assert picked.json()["databases"] == {"acme": ["shared01"]}
    bad = httpx.put(f"{base}/api/datadog/databases", json={"databases": {"acme": "shared01"}})
    assert bad.status_code == 400
