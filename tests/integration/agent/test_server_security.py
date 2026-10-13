from __future__ import annotations

import httpx
from helpers.sessions import BASE_URL, seed_session


def test_the_api_lists_instances_and_rejects_cross_site_posts(agent_server):
    seed_session(BASE_URL)
    rows = httpx.get(f"{agent_server}/api/instances").json()
    assert rows[0]["alias"] == "acme" and rows[0]["valid"]

    forged = httpx.post(f"{agent_server}/api/runs", content="{}", headers={"Content-Type": "text/plain"})
    assert forged.status_code == 403
    foreign = httpx.post(f"{agent_server}/api/runs", json={}, headers={"Origin": "https://evil.test"})
    assert foreign.status_code == 403


def test_a_local_page_on_another_port_is_refused(agent_server):
    other = httpx.get(f"{agent_server}/api/runs", headers={"Origin": "http://127.0.0.1:3000"})
    assert other.status_code == 403


def test_cross_site_requests_are_refused(agent_server):
    assert httpx.get(f"{agent_server}/api/runs", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert httpx.get(f"{agent_server}/api/runs", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
