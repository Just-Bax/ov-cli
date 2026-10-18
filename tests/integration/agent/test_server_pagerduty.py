from __future__ import annotations

import threading

import httpx
import pytest
from helpers.fake_pagerduty import KEY, install_fake_pagerduty, link_pagerduty


@pytest.fixture
def linked(monkeypatch, logged_in):
    return link_pagerduty(install_fake_pagerduty(monkeypatch))


def test_the_api_never_returns_the_key(linked):
    from ov.agent.api.server import AgentServer, Handler

    httpd = AgentServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    try:
        status = httpx.get(f"{base}/api/pagerduty")
        assert status.json()["connected"] and KEY not in status.text

        bad = httpx.post(f"{base}/api/pagerduty/connect", json={"account": "x", "apiKey": "nope"})
        assert bad.status_code == 400

        assert httpx.delete(f"{base}/api/pagerduty").json()["connected"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
