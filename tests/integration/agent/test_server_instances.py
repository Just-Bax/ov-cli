from __future__ import annotations

import httpx
from helpers.sessions import BASE_URL, seed_session

from ov.agent.instances.ovproc import OvResult


def test_instance_sign_in_keeps_the_url_and_tenant(agent_server, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "ov.agent.instances.ovproc.run_ov", lambda args, **k: seen.append(args) or OvResult(0, "ok", "")
    )

    url = "http://portal.customer.example:8443/ov"
    res = httpx.post(f"{agent_server}/api/instances/login", json={"url": url, "tenant": "North"})
    assert res.json()["ok"]
    assert seen[-1][:2] == ["login", url]
    assert seen[-1][-2:] == ["--tenant", "North"]

    httpx.post(f"{agent_server}/api/instances/login", json={"url": url})
    assert "--tenant" not in seen[-1] and "--remember" not in seen[-1]

    httpx.post(f"{agent_server}/api/instances/login", json={"url": url, "remember": True})
    assert seen[-1][-2:] == ["--remember", "30"]


def test_instance_sign_in_passes_a_token_on_stdin(agent_server, monkeypatch):
    seen: list[tuple[list[str], str | None]] = []

    def fake(args, **kwargs):
        seen.append((args, kwargs.get("stdin")))
        return OvResult(0, "ok", "")

    monkeypatch.setattr("ov.agent.instances.ovproc.run_ov", fake)
    url = "https://acme.onevizion.test"
    res = httpx.post(f"{agent_server}/api/instances/login", json={"url": url, "token": "K:S", "remember": True})
    assert res.json()["ok"]
    assert seen[-1] == (["login", url, "--keep-current", "--timeout", "280", "--token", "-"], "K:S")

    both = httpx.post(f"{agent_server}/api/instances/login", json={"url": url, "token": "K:S", "tenant": "x"})
    assert both.status_code == 400


def test_an_instance_can_be_removed(agent_server, monkeypatch):
    seed_session(BASE_URL)
    seen: list[list[str]] = []

    def fake(args, **kwargs):
        seen.append(args)
        assert kwargs.get("read_only") is False
        from ov.onevizion import session as session_store

        session_store.remove(args[1])
        return OvResult(0, "{}", "")

    monkeypatch.setattr("ov.agent.api.routes.instances.run_ov", fake)
    rows = httpx.post(f"{agent_server}/api/instances/logout", json={"alias": "acme"}).json()
    assert seen == [["logout", "acme", "--json"]] and rows == []

    missing = httpx.post(f"{agent_server}/api/instances/logout", json={"alias": "acme"})
    assert missing.status_code == 404
