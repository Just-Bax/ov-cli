from __future__ import annotations

import httpx


def test_settings_reject_unknown_keys(agent_server):
    refused = httpx.put(f"{agent_server}/api/settings", json={"defaultModel": "m", "secret": "x"})
    assert refused.status_code == 400 and "secret" in refused.json()["error"]
    saved = httpx.put(f"{agent_server}/api/settings", json={"defaultModel": "m"}).json()
    assert saved["defaultModel"] == "m"
