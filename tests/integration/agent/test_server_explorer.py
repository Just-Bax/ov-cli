from __future__ import annotations

import httpx
import pytest
from helpers.fake_reader import install_fake_reader


@pytest.fixture
def reader(monkeypatch):
    yield from install_fake_reader(monkeypatch)


def test_explorer_api(agent_server, reader):
    ok = httpx.get(f"{agent_server}/api/explorer/source", params={"instance": "acme", "id": "rule:1"})
    assert ok.status_code == 200
    assert ok.json()["sections"][0]["title"] == "Rule SQL"
    bad = httpx.get(f"{agent_server}/api/explorer/source", params={"instance": "acme", "id": "x"})
    assert bad.status_code == 400
    runs = httpx.get(f"{agent_server}/api/explorer/activity", params={"instance": "acme", "id": "rule:1"})
    assert runs.json()[0]["status"] == "Error"
