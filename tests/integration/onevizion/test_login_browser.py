from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ov.onevizion.login import browser_is_installed, interactive_login

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(not browser_is_installed(), reason="chromium is not installed for playwright"),
]

SESSION_COOKIE = "JSESSIONID=mock-session; Path=/; HttpOnly"
CSRF_HEADER = "X-CSRF-TOKEN"
CSRF_VALUE = "csrf-mock"
BEARER = "MOCKACCESS:MOCKSECRET"
EXPIRES = "2100-01-01T00:00:00"


LATE_REDIRECT = (
    b"<html><body>signing in<script>setTimeout(function(){location.href='/Default.do';}, 2500);</script></body></html>"
)

NEW_TAB = (
    b"<html><body>signing in"
    b"<script>setTimeout(function(){window.open('/Default.do', '_blank');}, 2500);</script>"
    b"</body></html>"
)


class Handler(BaseHTTPRequestHandler):
    signed_in = False
    slow_redirect = False
    new_tab = False

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: bytes = b"", content_type: str = "text/html", **headers):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _has_session(self) -> bool:
        return "mock-session" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        routes = {"/Login.do": self._login, "/Default.do": self._app, "/CsrfToken.do": self._csrf}
        route = routes.get(self.path.split("?")[0])
        if route is None:
            self._send(404)
        else:
            route()

    def _login(self):
        if Handler.new_tab:
            self._send(200, NEW_TAB)
        elif Handler.slow_redirect:
            self._send(200, LATE_REDIRECT)
        else:
            Handler.signed_in = True
            self._send(302, b"", Set_Cookie=SESSION_COOKIE, Location="/Default.do")

    def _app(self):
        Handler.signed_in = True
        self._send(200, b"<html><body>app</body></html>", Set_Cookie=SESSION_COOKIE)

    def _csrf(self):
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            self._send(404)
        elif not self._has_session():
            self._send(302, b"", Location="/Login.do")
        else:
            body = json.dumps({"headerName": CSRF_HEADER, "token": CSRF_VALUE, "parameterName": "_csrf"}).encode()
            self._send(200, body, content_type="application/json")

    def do_POST(self):
        if self.path != "/widget/GenerateApiTokenForWebSession":
            self._send(404)
            return
        if not self._has_session():
            self._send(302, b"", Location="/Login.do")
            return
        if self.headers.get(CSRF_HEADER) != CSRF_VALUE:
            self._send(403)
            return

        body = json.dumps({"bearerToken": BEARER, "expirationTime": EXPIRES}).encode()
        self._send(200, body, content_type="application/json")


@pytest.fixture
def instance():
    Handler.signed_in = False
    Handler.slow_redirect = False
    Handler.new_tab = False
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_a_real_browser_completes_the_token_exchange(instance, ov_home):
    progress: list[str] = []
    session = interactive_login(
        instance,
        timeout_ms=30_000,
        on_progress=progress.append,
        headless=True,
    )

    assert session.bearer_token == BEARER
    assert session.expires_text == EXPIRES
    assert session.base_url == instance
    assert session.cookies.get("JSESSIONID") == "mock-session"


def test_a_sign_in_that_completes_after_goto_is_still_noticed(instance, ov_home):
    Handler.slow_redirect = True
    session = interactive_login(instance, timeout_ms=30_000, headless=True)
    assert session.bearer_token == BEARER


def test_the_app_arriving_in_a_second_tab_is_found(instance, ov_home):
    Handler.new_tab = True
    session = interactive_login(instance, timeout_ms=30_000, headless=True)
    assert session.bearer_token == BEARER
