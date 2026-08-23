from __future__ import annotations

import httpx
import pytest
from conftest import BASE_URL, Recorder

from ov.client import Client, api_path
from ov.errors import ApiError, Forbidden, NotFound, SessionExpired, Unreachable
from ov.session import Session


def session(mode: str = "session", token: str = "ACCESS:SECRET") -> Session:
    return Session(
        base_url=BASE_URL,
        mode=mode,
        cookies={"JSESSIONID": "abc"} if mode == "session" else {},
        bearer_token=token,
        expires_at=4102444800.0,
    )


def client(recorder: Recorder, mode: str = "session") -> Client:
    return Client(session(mode), transport=recorder.transport)


def test_api_path_accepts_three_spellings():
    assert api_path("/v3/users") == "/api/v3/users"
    assert api_path("v3/users") == "/api/v3/users"
    assert api_path("/api/v3/users") == "/api/v3/users"


def test_api_calls_carry_the_bearer_token():
    recorder = Recorder()
    with client(recorder) as api:
        api.api("GET", "/v3/users")
    assert recorder.last.headers["authorization"] == "Bearer ACCESS:SECRET"
    assert recorder.last.url.path == "/api/v3/users"


def test_web_calls_carry_cookies_and_no_bearer():
    """An Authorization header would route the schema request to the token
    chain, which rejects a web session token as the wrong type."""
    recorder = Recorder()
    with client(recorder) as api:
        api.web_get("/api/docs/openapi/v3")
    assert "authorization" not in recorder.last.headers
    assert "JSESSIONID=abc" in recorder.last.headers["cookie"]


def test_a_login_redirect_is_read_as_an_expired_session():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Login.do":
            return httpx.Response(200, text="<html>login</html>", request=request)
        return httpx.Response(302, headers={"location": f"{BASE_URL}/Login.do"}, request=request)

    with Client(session(), transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(SessionExpired):
            api.web_get("/api/docs/openapi/v3")


def test_a_rejected_token_is_reminted_once_and_the_call_retried():
    calls = {"api": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/CsrfToken.do":
            return httpx.Response(
                200,
                json={"headerName": "X-CSRF-TOKEN", "token": "csrf-1", "parameterName": "_csrf"},
                request=request,
            )
        if path == "/widget/GenerateApiTokenForWebSession":
            return httpx.Response(
                200,
                json={"bearerToken": "NEW:KEY", "expirationTime": "2100-01-01T00:00:00"},
                request=request,
            )
        calls["api"] += 1
        if calls["api"] == 1:
            return httpx.Response(401, text="expired", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    stored = session()
    with Client(stored, transport=httpx.MockTransport(handler)) as api:
        response = api.api("GET", "/v3/users")

    assert response.json() == {"ok": True}
    assert stored.bearer_token == "NEW:KEY"
    assert calls["api"] == 2


def test_a_static_token_is_never_reminted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="nope", request=request)

    with Client(session("token"), transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(SessionExpired):
            api.api("GET", "/v3/users")


def test_status_codes_map_onto_distinct_errors():
    cases = {403: Forbidden, 404: NotFound, 500: ApiError}
    for status, expected in cases.items():
        recorder = Recorder()
        recorder.route("GET", "/api/v3/users", status, "no")
        with client(recorder) as api:
            with pytest.raises(expected):
                api.api("GET", "/v3/users")


def test_a_text_plain_error_body_becomes_the_message():
    """OneVizion answers API errors with text/plain, so the body is the message."""
    recorder = Recorder()
    recorder.route("GET", "/api/v3/users", 400, "Trackor Type [X] not found")
    with client(recorder) as api:
        with pytest.raises(ApiError, match="Trackor Type"):
            api.api("GET", "/v3/users")


def test_an_html_error_body_is_not_shown_as_the_message():
    recorder = Recorder()
    recorder.route("GET", "/api/v3/users", 500, "<html><body>Error</body></html>")
    with client(recorder) as api:
        with pytest.raises(ApiError, match="HTTP 500"):
            api.api("GET", "/v3/users")


def test_an_unreachable_instance_is_reported_not_raised_raw():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("getaddrinfo failed", request=request)

    with Client(session(), transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(Unreachable, match="Could not reach"):
            api.api("GET", "/v3/users")


def test_a_timeout_says_which_setting_to_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with Client(session(), transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(Unreachable, match="timeout_seconds"):
            api.api("GET", "/v3/users")
