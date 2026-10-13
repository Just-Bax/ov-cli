from __future__ import annotations

import json

import httpx

from ov.onevizion.session import Session

from .sessions import BASE_URL

MENU = {"100": "North", "200": "Harbor", "300": "Metro"}

PAGE = (
    "<html><head><script>\n"
    '  var whatsNewUrl = "";\n'
    f"  var programMenu = {json.dumps(MENU)};\n"
    '  var loginAsUrl = "";\n'
    "</script></head><body>app</body></html>"
)


def recording_transport(calls: list[str], first_call_401: bool = False):
    state = {"api": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(f"{request.method} {path}")

        if path == "/CsrfToken.do":
            return httpx.Response(
                200,
                json={"headerName": "X-CSRF-TOKEN", "token": "csrf-1", "parameterName": "_csrf"},
                request=request,
            )
        if path == "/program/FormProg.do":
            calls[-1] += f"?pid={request.url.params.get('pid')}"
            return httpx.Response(200, text="", request=request)
        if path == "/widget/GenerateApiTokenForWebSession":
            return httpx.Response(
                200,
                json={"bearerToken": "TENANT:KEY", "expirationTime": "2100-01-01T00:00:00"},
                request=request,
            )
        if path == "/Default.do":
            return httpx.Response(200, text=PAGE, request=request)

        state["api"] += 1
        if first_call_401 and state["api"] == 1:
            return httpx.Response(401, text="expired", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    return httpx.MockTransport(handler)


def tenant_session() -> Session:
    return Session(
        base_url=BASE_URL,
        tenant="North",
        tenant_id="100",
        cookies={"JSESSIONID": "abc"},
        bearer_token="OLD:KEY",
        expires_at=4102444800.0,
    )
