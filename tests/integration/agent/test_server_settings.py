from __future__ import annotations

import httpx


def test_settings_reject_unknown_keys(agent_server):
    refused = httpx.put(f"{agent_server}/api/settings", json={"defaultModel": "m", "secret": "x"})
    assert refused.status_code == 400 and "secret" in refused.json()["error"]
    saved = httpx.put(f"{agent_server}/api/settings", json={"defaultModel": "m"}).json()
    assert saved["defaultModel"] == "m"


def test_status_lists_every_provider_and_settings_hold_the_profile(agent_server, monkeypatch):
    monkeypatch.setattr("ov.agent.integrations.copilot.user", lambda: "someone")
    monkeypatch.setattr("ov.agent.integrations.claude.account", lambda: {"installed": False, "signedIn": False})

    status = httpx.get(f"{agent_server}/api/status").json()
    assert status["provider"] == "copilot"
    assert [(p["id"], p["costUnit"], p["account"]["signedIn"]) for p in status["providers"]] == [
        ("claude", "usd", False),
        ("copilot", "credits", True),
    ]

    saved = httpx.put(f"{agent_server}/api/settings", json={"fullName": "Ada", "instructions": "Be brief."}).json()
    assert (saved["fullName"], saved["instructions"]) == ("Ada", "Be brief.")

    refused = httpx.put(f"{agent_server}/api/settings", json={"provider": "nope"})
    assert refused.status_code == 400 and "Unknown provider: nope" in refused.json()["error"]

    blank = httpx.put(f"{agent_server}/api/settings", json={"fullName": "   "})
    assert blank.status_code == 400 and "full name is required" in blank.json()["error"]


def test_each_provider_keeps_its_own_models_across_switches(agent_server):
    settings = f"{agent_server}/api/settings"
    httpx.put(settings, json={"defaultModel": "gpt-main", "fastModel": "gpt-fast"})

    on_claude = httpx.put(settings, json={"provider": "claude"}).json()
    httpx.put(settings, json={"fastModel": "haiku"})
    back = httpx.put(settings, json={"provider": "copilot"}).json()
    again = httpx.put(settings, json={"provider": "claude"}).json()

    assert on_claude["provider"] == "claude" and on_claude["defaultModel"] != "gpt-main"
    assert (back["defaultModel"], back["fastModel"]) == ("gpt-main", "gpt-fast")
    assert again["fastModel"] == "haiku"
