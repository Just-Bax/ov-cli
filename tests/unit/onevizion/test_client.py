from __future__ import annotations

import httpx
import pytest
from helpers.recorder import Recorder
from helpers.sessions import BASE_URL

from ov.core.errors import ApiError, Forbidden, NotFound, SessionExpired, Unreachable
from ov.onevizion.client import Client, api_path
from ov.onevizion.session import Session


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


def test_api_path_may_step_out_only_to_the_file_download():
    assert api_path("/../efiles/EFileGetBlobFromDb.do?id=7") == "/efiles/EFileGetBlobFromDb.do?id=7"
    assert api_path("/api/../efiles/EFileGetBlobFromDb.do?id=7") == "/efiles/EFileGetBlobFromDb.do?id=7"


def test_api_calls_carry_the_bearer_token():
    recorder = Recorder()
    with client(recorder) as api:
        api.api("GET", "/v3/users")
    assert recorder.last.headers["authorization"] == "Bearer ACCESS:SECRET"
    assert recorder.last.url.path == "/api/v3/users"


def test_web_calls_carry_cookies_and_no_bearer():
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

    with Client(session(), transport=httpx.MockTransport(handler)) as api, pytest.raises(SessionExpired):
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


def test_a_crashing_token_endpoint_is_an_api_error_not_an_expired_session():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/CsrfToken.do":
            return httpx.Response(200, json={"headerName": "X-CSRF-TOKEN", "token": "csrf-1"}, request=request)
        if path == "/widget/GenerateApiTokenForWebSession":
            return httpx.Response(500, json={"message": "Encryption key is not set"}, request=request)
        return httpx.Response(401, text="expired", request=request)

    with (
        Client(session(), transport=httpx.MockTransport(handler)) as api,
        pytest.raises(ApiError, match="Encryption key is not set"),
    ):
        api.api("GET", "/v3/users")


def test_a_static_token_is_never_reminted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="nope", request=request)

    with Client(session("token"), transport=httpx.MockTransport(handler)) as api, pytest.raises(SessionExpired):
        api.api("GET", "/v3/users")


def test_status_codes_map_onto_distinct_errors():
    cases = {403: Forbidden, 404: NotFound, 500: ApiError}
    for status, expected in cases.items():
        recorder = Recorder()
        recorder.route("GET", "/api/v3/users", status, "no")
        with client(recorder) as api, pytest.raises(expected):
            api.api("GET", "/v3/users")


def test_a_text_plain_error_body_becomes_the_message():
    recorder = Recorder()
    recorder.route("GET", "/api/v3/users", 400, "Trackor Type [X] not found")
    with client(recorder) as api, pytest.raises(ApiError, match="Trackor Type"):
        api.api("GET", "/v3/users")


def test_an_html_error_body_is_not_shown_as_the_message():
    recorder = Recorder()
    recorder.route("GET", "/api/v3/users", 500, "<html><body>Error</body></html>")
    with client(recorder) as api, pytest.raises(ApiError, match="HTTP 500"):
        api.api("GET", "/v3/users")


def test_an_unreachable_instance_is_reported_not_raised_raw():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("getaddrinfo failed", request=request)

    transport = httpx.MockTransport(handler)
    with Client(session(), transport=transport) as api, pytest.raises(Unreachable, match="Could not reach"):
        api.api("GET", "/v3/users")


def test_a_timeout_says_which_setting_to_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    transport = httpx.MockTransport(handler)
    with Client(session(), transport=transport) as api, pytest.raises(Unreachable, match="timeout_seconds"):
        api.api("GET", "/v3/users")


@pytest.mark.parametrize(
    ("response", "alive"),
    [
        (httpx.Response(200, text="<html>Trackor Browser</html>"), True),
        (httpx.Response(302, headers={"Location": "/Login.do"}), False),
        (httpx.Response(200, text='<form action="/Login.do">'), False),
    ],
)
def test_the_web_session_is_alive_only_when_a_signed_in_page_opens(response, alive):
    with Client(session(), transport=httpx.MockTransport(lambda _: response)) as api:
        assert api.web_session_alive() is alive


def test_a_session_without_cookies_has_no_web_session():
    with Client(session("token"), transport=httpx.MockTransport(lambda _: httpx.Response(500))) as api:
        assert api.web_session_alive() is False


def test_a_web_form_post_carries_the_csrf_token():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/CsrfToken.do":
            return httpx.Response(200, json={"headerName": "X-CSRF-TOKEN", "token": "csrf-1"}, request=request)
        seen.append(request)
        return httpx.Response(200, text="42", request=request)

    with Client(session(), transport=httpx.MockTransport(handler)) as api:
        response = api.web_post_form("/admin/plsqlblock/Execution.do", {"plsql": "begin null; end;"}, 5.0)

    assert response.text == "42"
    assert seen[0].headers["x-csrf-token"] == "csrf-1"
    assert seen[0].content == b"plsql=begin+null%3B+end%3B"


@pytest.mark.parametrize("mode", ["remembered", "token"])
def test_a_web_form_post_works_for_a_stored_token_with_live_cookies(mode):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/CsrfToken.do":
            return httpx.Response(200, json={"headerName": "X-CSRF-TOKEN", "token": "csrf-1"}, request=request)
        return httpx.Response(200, text="ok", request=request)

    stored = Session(base_url=BASE_URL, mode=mode, cookies={"JSESSIONID": "abc"}, bearer_token="KEEP:ME")
    with Client(stored, transport=httpx.MockTransport(handler)) as api:
        assert api.web_post_form("/admin/plsqlblock/Execution.do", {"plsql": "begin null; end;"}, 5.0).text == "ok"


def test_a_rejected_web_post_never_ends_the_stored_token(monkeypatch):
    ended: list = []
    monkeypatch.setattr("ov.onevizion.client.session_store.mark_ended", ended.append)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/CsrfToken.do":
            return httpx.Response(200, json={"headerName": "X-CSRF-TOKEN", "token": "csrf-1"}, request=request)
        return httpx.Response(401, text="", request=request)

    stored = Session(base_url=BASE_URL, mode="remembered", cookies={"JSESSIONID": "abc"}, bearer_token="KEEP:ME")
    with Client(stored, transport=httpx.MockTransport(handler)) as api, pytest.raises(SessionExpired):
        api.web_post_form("/admin/plsqlblock/Execution.do", {"plsql": "begin null; end;"}, 5.0)
    assert ended == []
