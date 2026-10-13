from __future__ import annotations

import httpx
from helpers.sessions import BASE_URL, seed_session


def test_the_api_reports_a_missing_map(agent_server):
    seed_session(BASE_URL)
    status = httpx.get(f"{agent_server}/api/graph/status", params={"instance": "acme"}).json()
    assert status == {"state": "none"}
    missing = httpx.get(f"{agent_server}/api/graph", params={"instance": "acme"})
    assert missing.status_code == 404
    unknown = httpx.get(f"{agent_server}/api/graph/status", params={"instance": "nope"})
    assert unknown.status_code == 404
