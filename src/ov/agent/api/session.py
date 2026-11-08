from __future__ import annotations

import hmac
import secrets
from http.cookies import SimpleCookie

from ov.core.paths import agent_dir, write_atomic

TOKEN_BYTES = 32
TOKEN_FILE = "session"
COOKIE = "ov_session"
LINK_PARAM = "session"
COOKIE_ATTRIBUTES = "HttpOnly; SameSite=Strict; Path=/"


def token() -> str:
    path = agent_dir() / TOKEN_FILE
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()

    created = secrets.token_urlsafe(TOKEN_BYTES)
    write_atomic(path, created)
    return created


def link(url: str, session_token: str) -> str:
    return f"{url}/?{LINK_PARAM}={session_token}"


def set_cookie(session_token: str) -> str:
    return f"{COOKIE}={session_token}; {COOKIE_ATTRIBUTES}"


def matches(given: str | None, session_token: str) -> bool:
    return given is not None and hmac.compare_digest(given.encode(), session_token.encode())


def from_cookies(header: str | None) -> str | None:
    if not header:
        return None
    morsel = SimpleCookie(header).get(COOKIE)
    return morsel.value if morsel else None
