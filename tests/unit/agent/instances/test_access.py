from __future__ import annotations

import httpx
import pytest

from ov.agent.instances import access
from ov.onevizion import session as session_store
from ov.onevizion.client import Client

PRIVS = [
    {"security_group": "TEST_SQL", "priv": "R"},
    {"security_group": "BPL_EXP_IMP", "priv": "READ"},
    {"security_group": "METADATA", "priv": "NONE"},
    {"security_group": "DB_DOCS", "priv": "R"},
]
MAIN_PAGE = "<script>var platformEditionKey = 'ENTERPRISE';</script>"


def _serve(monkeypatch, page: str | None, privs: list[dict] = PRIVS) -> list[str]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v3/privs":
            return httpx.Response(200, json=privs, request=request)
        if request.url.path == "/api/v3/server_info":
            return httpx.Response(200, json={"version": "26.14.2"}, request=request)
        if request.url.path == "/Login.do":
            return httpx.Response(200, text="login", request=request)
        if page is None:
            return httpx.Response(302, headers={"location": "https://acme.onevizion.test/Login.do"}, request=request)
        return httpx.Response(200, text=page, request=request)

    def client(alias: str) -> Client:
        return Client(session_store.load(alias), transport=httpx.MockTransport(handler))

    monkeypatch.setattr(access, "open_client", client)
    return seen


def test_privileges_are_read_with_their_letters(logged_in, monkeypatch):
    _serve(monkeypatch, MAIN_PAGE)
    assert access.allows("acme", "testSql") is None

    found = access.check("acme")

    assert (found["version"], found["edition"]) == ("26.14.2", "ENTERPRISE")
    assert found["testSql"] and found["export"] and found["import"]
    assert not found["metadata"] and not found["dbSource"] and not found["mcp"]
    assert access.allows("acme", "import") is True
    assert access.describe("acme") == (
        "platform 26.14.2 Enterprise edition; can use Test SQL, component export, component import; "
        "cannot use schema metadata, platform DB source, MCP server"
    )


def test_an_expired_web_session_keeps_the_edition_read_before(logged_in, monkeypatch):
    _serve(monkeypatch, MAIN_PAGE)
    access.check("acme")
    _serve(monkeypatch, None, [{"security_group": "TEST_SQL", "priv": "NONE"}])
    found = access.check("acme")
    assert found["edition"] == "ENTERPRISE" and found["testSql"] is False
    assert access.status("acme")["checking"] is False


def test_a_failed_check_is_explained_and_shown(logged_in, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "No WEB_SERVICES privilege"}, request=request)

    monkeypatch.setattr(
        access, "open_client", lambda alias: Client(session_store.load(alias), transport=httpx.MockTransport(handler))
    )

    with pytest.raises(access.AccessError, match="No WEB_SERVICES privilege"):
        access.check("acme")
    assert access.status("acme")["error"] == "No WEB_SERVICES privilege"
    assert access.describe("acme") == access.NOT_CHECKED


def test_a_signed_out_instance_is_not_shown_as_an_access_error(logged_in, monkeypatch):
    from ov.core.errors import SessionExpired

    def signed_out(alias):
        raise SessionExpired("the web session ended")

    monkeypatch.setattr(access, "_read", signed_out)

    with pytest.raises(access.AccessError, match="is signed out"):
        access.check("acme")
    assert "error" not in access.status("acme")
