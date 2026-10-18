from __future__ import annotations

import pytest
from helpers.cli import payload
from helpers.sessions import BASE_URL
from helpers.tenants import recording_transport, tenant_session

from ov.onevizion import session as session_store
from ov.onevizion.session import Session


@pytest.fixture
def tenant_server(monkeypatch):
    calls: list[str] = []
    transport = recording_transport(calls)

    from ov.cli import context as context_module
    from ov.onevizion.client import Client as RealClient

    def build(config, session):
        return RealClient(session, timeout=float(config.timeout_seconds), transport=transport)

    monkeypatch.setattr(context_module, "build_client", build)
    monkeypatch.setattr("ov.cli.commands.auth.build_client", build)
    return calls


def test_tenants_lists_them_and_marks_the_current(capsys, ov_home, tenant_server):
    session_store.save(tenant_session())
    code, data = payload(capsys, "tenants", "--json")
    assert code == 0
    assert [r["name"] for r in data] == ["Harbor", "Metro", "North"]
    assert [r["current"] for r in data] == [False, False, True]


def test_tenants_is_refused_for_an_api_token(capsys, ov_home, tenant_server):
    session_store.save(Session(base_url=BASE_URL, mode="token", bearer_token="K:S"))
    code, data = payload(capsys, "tenants", "--json")
    assert code == 1
    assert "browser sign-in" in data["error"]


def test_login_with_a_tenant_is_refused_for_an_api_token(capsys, ov_home, tenant_server):
    code, data = payload(capsys, "login", BASE_URL, "--token", "K:S", "--tenant", "North", "--no-spec", "--json")
    assert code == 1
    assert "--tenant needs a browser sign-in" in data["error"]


def test_a_tenant_login_is_stored_under_a_tenant_alias(capsys, ov_home, tenant_server, monkeypatch):
    monkeypatch.setattr(
        "ov.cli.commands.auth._browser_login",
        lambda ctx, base_url: Session(base_url=base_url, cookies={"JSESSIONID": "abc"}, bearer_token="SIGNIN:KEY"),
    )

    code, data = payload(capsys, "login", BASE_URL, "--tenant", "North", "--no-spec", "--json")

    assert code == 0
    assert data["alias"] == "acme/north"
    assert data["tenant"] == "North"
    assert sorted(session_store.all_sessions()) == ["acme/north"]
    assert session_store.load("acme/north").bearer_token == "TENANT:KEY"
