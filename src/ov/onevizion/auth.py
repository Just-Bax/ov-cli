from __future__ import annotations

import json
from typing import Any

import httpx

from ov.core.errors import ApiError, Forbidden, SessionExpired
from ov.onevizion.session import Session, expiry_to_epoch
from ov.onevizion.tenants import DEFAULT_PATH, SWITCH_PATH, parse_program_menu

LOGIN_PATH = "/Login.do"
CSRF_PATH = "/CsrfToken.do"
MINT_PATH = "/widget/GenerateApiTokenForWebSession"

AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
SERVER_ERROR = 500
MESSAGE_LIMIT = 1000
MESSAGE_KEYS = ("message", "error", "detail", "description")

NO_WIDGET_PRIV = (
    "Minting an API token needs the WIDGET module at Read. "
    "Ask an administrator for it, or use 'ov login --token accessKey:secretKey' "
    "with a token from Admin > Auth Tokens."
)


def mint_web_session_token(http: httpx.Client, session: Session) -> Session:
    if session.tenant_id:
        switch_tenant(http, session.tenant_id)

    response = http.post(MINT_PATH, headers=_csrf_headers(http))
    _guard(response)
    if response.status_code == 403:
        raise Forbidden(NO_WIDGET_PRIV)
    if response.status_code >= SERVER_ERROR:
        message = server_message(response.text)
        raise ApiError(response.status_code, message, message, str(response.url))
    if response.status_code >= 400:
        raise SessionExpired(f"token endpoint returned {response.status_code}")

    payload = _json(response, MINT_PATH)
    token = payload.get("bearerToken")
    expires_text = payload.get("expirationTime")
    if not token or not expires_text:
        raise SessionExpired("token endpoint returned no bearerToken or expirationTime")

    session.bearer_token = token
    session.expires_text = expires_text
    session.expires_at = expiry_to_epoch(expires_text)
    session.cookies = _cookies_of(http, session.cookies)
    return session


def switch_tenant(http: httpx.Client, tenant_id: str) -> None:
    response = http.post(SWITCH_PATH, params={"pid": tenant_id}, headers=_csrf_headers(http))
    _guard(response)
    if response.status_code == 403:
        raise Forbidden(f"Not allowed into tenant {tenant_id}. It needs a user with your email address.")
    if response.status_code >= 400:
        raise SessionExpired(f"tenant switch returned {response.status_code}")


def list_tenants(http: httpx.Client) -> dict[str, str]:
    response = http.get(DEFAULT_PATH, headers={"Accept": "text/html"})
    _guard(response)
    if response.status_code >= 400:
        raise SessionExpired(f"{DEFAULT_PATH} returned {response.status_code}")
    return parse_program_menu(response.text)


def server_message(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("<"):
        return ""
    try:
        payload = json.loads(stripped)
    except ValueError:
        return stripped[:MESSAGE_LIMIT]
    if not isinstance(payload, dict):
        return stripped[:MESSAGE_LIMIT]
    return next((str(payload[key]) for key in MESSAGE_KEYS if payload.get(key)), "")


def _csrf_headers(http: httpx.Client) -> dict[str, str]:
    response = http.get(CSRF_PATH, headers=AJAX_HEADERS)
    _guard(response)
    if response.status_code >= 400:
        raise SessionExpired(f"CSRF endpoint returned {response.status_code}")

    payload = _json(response, CSRF_PATH)
    header = payload.get("headerName")
    token = payload.get("token")
    if not header or not token:
        raise SessionExpired("CSRF endpoint returned no token")
    return {**AJAX_HEADERS, header: token}


def _guard(response: httpx.Response) -> None:
    if LOGIN_PATH.lower() in str(response.url).lower():
        raise SessionExpired("redirected to the login page")


def _json(response: httpx.Response, path: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        raise SessionExpired(f"{path} did not return JSON") from None
    if not isinstance(payload, dict):
        raise SessionExpired(f"{path} returned {type(payload).__name__}, expected an object")
    return payload


def _cookies_of(http: httpx.Client, previous: dict[str, str]) -> dict[str, str]:
    current = dict(previous)
    for cookie in http.cookies.jar:
        if cookie.value:
            current[cookie.name] = cookie.value
    return current
