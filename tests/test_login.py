from __future__ import annotations

import math
from typing import Any

import pytest

from ov.errors import LoginFailed
from ov.login import _await_token, _looks_signed_in, _mint

BASE_URL = "https://acme.onevizion.test"
HOST = "acme.onevizion.test"
PROVIDER = "https://login.microsoftonline.com/common/oauth2/authorize"

CSRF = {"headerName": "X-CSRF-TOKEN", "token": "csrf-1", "parameterName": "_csrf"}
MINTED = {"bearerToken": "ACCESS:SECRET", "expirationTime": "2100-01-01T00:00:00"}

DESTROYED = "Page.evaluate: Execution context was destroyed, most likely because of a navigation"


class FakePage:
    """A browser tab: a URL that can advance, and a script result."""

    def __init__(self, urls: list[str], result: Any = None, closed: bool = False) -> None:
        self.urls = urls
        self.result = result
        self.closed = closed
        self.evaluated = 0

    @property
    def url(self) -> str:
        return self.urls[0] if len(self.urls) == 1 else self.urls.pop(0)

    def is_closed(self) -> bool:
        return self.closed

    def evaluate(self, script: str, arg: Any = None) -> Any:
        self.evaluated += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeResponse:
    def __init__(self, status: int = 200, payload: Any = None) -> None:
        self.status = status
        self._payload = payload

    @property
    def ok(self) -> bool:
        return self.status < 400

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeRequest:
    """Stands in for the browser context's APIRequestContext.

    `rejects` is how many rounds happen before the session is real, which is
    what a mid-handshake page on the instance's own host looks like.
    """

    def __init__(self, rejects: float = 0, mint_status: int = 200) -> None:
        self.rejects = rejects
        self.mint_status = mint_status
        self.rounds = 0
        self.calls: list[str] = []

    def get(self, url: str, headers: Any = None) -> FakeResponse:
        self.calls.append(f"GET {url}")
        if self.rounds < self.rejects:
            self.rounds += 1
            return FakeResponse(401)
        return FakeResponse(200, CSRF)

    def post(self, url: str, headers: Any = None) -> FakeResponse:
        self.calls.append(f"POST {url}")
        if self.mint_status != 200:
            return FakeResponse(self.mint_status)
        return FakeResponse(200, MINTED)


class DeadRequest(FakeRequest):
    """The context request API is not always usable either."""

    def get(self, url: str, headers: Any = None) -> FakeResponse:
        raise RuntimeError("Target page, context or browser has been closed")


class FakeContext:
    def __init__(
        self, request: FakeRequest, pages: list[FakePage], browser_cookies: Any = None
    ) -> None:
        self.request = request
        self.pages = pages
        self.browser_cookies = browser_cookies if browser_cookies is not None else []

    def cookies(self) -> Any:
        return self.browser_cookies


def wait(context: FakeContext, timeout_ms: int = 10_000, report=None) -> dict[str, Any]:
    return _await_token(context, BASE_URL, HOST, timeout_ms, report or (lambda _m: None))


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    monkeypatch.setattr("ov.login.POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr("ov.login.PROGRESS_EVERY_SECONDS", 0)


# --- deciding whether a tab is signed in ---


def test_the_identity_providers_domain_is_never_minted_against():
    """The browser spends most of an SSO login on someone else's host."""
    assert not _looks_signed_in(PROVIDER, HOST)
    assert not _looks_signed_in("https://acme.okta.com/app/signin", HOST)


def test_the_instances_own_login_pages_do_not_count_as_signed_in():
    for path in ("/Login.do", "/LoginFull.do", "/saml/SSO", "/mfa/FormMfaAuthCode.do"):
        assert not _looks_signed_in(f"{BASE_URL}{path}", HOST)


def test_any_other_page_on_the_instance_counts():
    assert _looks_signed_in(f"{BASE_URL}/Home.do", HOST)
    assert _looks_signed_in(f"{BASE_URL}/", HOST)


# --- the exchange itself ---


def test_the_page_script_is_used_when_it_works():
    page = FakePage([f"{BASE_URL}/Home.do"], result=MINTED)
    request = FakeRequest()
    minted, error = _mint(FakeContext(request, [page]), page, BASE_URL)

    assert minted == MINTED
    assert error == ""
    assert request.calls == []


def test_a_destroyed_execution_context_falls_back_to_the_request_api():
    """An SSO redirect kills the page script mid-call; the exchange must not."""
    page = FakePage([f"{BASE_URL}/Home.do"], result=RuntimeError(DESTROYED))
    request = FakeRequest()
    minted, error = _mint(FakeContext(request, [page]), page, BASE_URL)

    assert minted == MINTED
    assert error == ""
    assert request.calls == [
        f"GET {BASE_URL}/CsrfToken.do",
        f"POST {BASE_URL}/widget/GenerateApiTokenForWebSession",
    ]


def test_every_failure_is_reported_together():
    page = FakePage([f"{BASE_URL}/Home.do"], result=RuntimeError(DESTROYED))
    minted, error = _mint(FakeContext(DeadRequest(), [page]), page, BASE_URL)

    assert minted is None
    for source in ("page:", "request:", "http:"):
        assert source in error


def test_a_missing_widget_privilege_from_the_page_fails_fast():
    page = FakePage([f"{BASE_URL}/Home.do"], result={"status": 403, "error": "page: 403"})
    with pytest.raises(LoginFailed, match="WIDGET"):
        _mint(FakeContext(FakeRequest(), [page]), page, BASE_URL)


def test_a_missing_widget_privilege_from_the_request_api_fails_fast():
    page = FakePage([f"{BASE_URL}/Home.do"], result=RuntimeError(DESTROYED))
    request = FakeRequest(mint_status=403)
    with pytest.raises(LoginFailed, match="WIDGET"):
        _mint(FakeContext(request, [page]), page, BASE_URL)


# --- waiting ---


def test_waiting_polls_until_the_instance_accepts_the_user():
    page = FakePage(
        [
            f"{BASE_URL}/Login.do",
            PROVIDER,
            "https://login.microsoftonline.com/common/login",
            f"{BASE_URL}/saml/SSO",
            f"{BASE_URL}/Home.do",
        ],
        result=MINTED,
    )
    assert wait(FakeContext(FakeRequest(), [page])) == MINTED
    # Nothing was attempted while the tab was off-instance or mid-handshake.
    assert page.evaluated == 1


def test_the_app_is_found_when_sso_opens_it_in_a_second_tab():
    """The tab we opened can be left parked on the provider's page."""
    parked = FakePage([PROVIDER], result=MINTED)
    app = FakePage([f"{BASE_URL}/Home.do"], result=MINTED)

    assert wait(FakeContext(FakeRequest(), [parked, app])) == MINTED
    assert parked.evaluated == 0
    assert app.evaluated == 1


def test_a_brief_bounce_through_the_instance_does_not_end_the_wait():
    """Some providers pass back through an app URL before the session exists."""
    page = FakePage(
        [f"{BASE_URL}/Home.do"],
        result={"error": "page: /CsrfToken.do returned 401"},
    )
    request = FakeRequest(rejects=2)
    assert wait(FakeContext(request, [page])) == MINTED


def test_closing_the_browser_is_reported_plainly():
    context = FakeContext(FakeRequest(), [FakePage([f"{BASE_URL}/Home.do"], closed=True)])
    with pytest.raises(LoginFailed, match="closed"):
        wait(context)


def test_a_signed_in_tab_that_keeps_being_refused_stops_waiting():
    """A permanent refusal must not cost the whole five minute timeout."""
    from ov import login as login_module

    page = FakePage([f"{BASE_URL}/Home.do"], result=RuntimeError(DESTROYED))
    request = FakeRequest(rejects=math.inf)

    with pytest.raises(LoginFailed) as caught:
        wait(FakeContext(request, [page]), timeout_ms=300_000)

    assert page.evaluated == login_module.STUCK_AFTER_ROUNDS

    message = str(caught.value)
    assert "would not issue an API token" in message
    assert "WIDGET" in message
    assert f"{BASE_URL}/Home.do" in message
    assert "--token" in message


def test_a_timeout_lists_the_open_tabs_and_the_last_error():
    page = FakePage([PROVIDER])
    with pytest.raises(LoginFailed) as caught:
        wait(FakeContext(FakeRequest(rejects=math.inf), [page]), timeout_ms=1)

    message = str(caught.value)
    assert "Timed out" in message
    assert PROVIDER in message
    assert "--verbose" in message


def test_a_login_stuck_on_the_providers_domain_says_so():
    page = FakePage([PROVIDER], result=MINTED)
    with pytest.raises(LoginFailed) as caught:
        wait(FakeContext(FakeRequest(rejects=math.inf), [page]), timeout_ms=1)
    assert PROVIDER in str(caught.value)


def test_plain_http_with_the_browsers_cookies_is_the_last_resort(monkeypatch):
    """The same exchange the CLI uses to refresh a token later on."""
    page = FakePage([f"{BASE_URL}/Home.do"], result=RuntimeError(DESTROYED))
    context = FakeContext(
        DeadRequest(), [page], browser_cookies=[{"name": "JSESSIONID", "value": "abc"}]
    )

    def mint(http, session):
        session.bearer_token = "HTTP:KEY"
        session.expires_text = "2100-01-01T00:00:00"

    monkeypatch.setattr("ov.auth.mint_web_session_token", mint)
    minted, error = _mint(context, page, BASE_URL)

    assert minted == {"bearerToken": "HTTP:KEY", "expirationTime": "2100-01-01T00:00:00"}
    assert error == ""


def test_the_http_fallback_waits_rather_than_guessing_without_cookies():
    page = FakePage([f"{BASE_URL}/Home.do"], result=RuntimeError(DESTROYED))
    context = FakeContext(DeadRequest(), [page], browser_cookies=[])

    minted, error = _mint(context, page, BASE_URL)
    assert minted is None
    assert "no cookies" in error


def test_a_missing_widget_privilege_over_plain_http_fails_fast(monkeypatch):
    from ov.errors import Forbidden

    page = FakePage([f"{BASE_URL}/Home.do"], result=RuntimeError(DESTROYED))
    context = FakeContext(
        DeadRequest(), [page], browser_cookies=[{"name": "JSESSIONID", "value": "abc"}]
    )

    def refuse(http, session):
        raise Forbidden("needs the WIDGET module at Read")

    monkeypatch.setattr("ov.auth.mint_web_session_token", refuse)
    with pytest.raises(LoginFailed, match="WIDGET"):
        _mint(context, page, BASE_URL)


def test_progress_reports_the_tabs_and_the_reason():
    page = FakePage([PROVIDER], result=MINTED)
    seen: list[str] = []

    with pytest.raises(LoginFailed):
        wait(FakeContext(FakeRequest(rejects=math.inf), [page]), timeout_ms=1, report=seen.append)

    assert seen, "the wait produced no progress output"
    assert HOST in seen[0]
    assert PROVIDER in seen[0]
