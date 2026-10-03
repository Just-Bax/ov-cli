from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote

import httpx

from . import API_PREFIX
from . import session as session_store
from .auth import LOGIN_PATH, list_tenants, mint_web_session_token
from .errors import ApiError, Forbidden, NotFound, ReadOnlyBlocked, SessionExpired, Unreachable
from .session import Session

USER_AGENT = "ov-cli"

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

READ_ONLY_POSTS = (
    re.compile(r"^/api/v3/trackor_types/[^/]+/trackors/search$"),
    re.compile(r"^/api/v3/sql/test$"),
    re.compile(r"^/api/v3/components/exports/run$"),
)

# Web UI actions are plain GETs, so read-only mode allows only these by path.
READ_ONLY_WEB_PATHS = (
    re.compile(r"^/api/docs/"),
    re.compile(r"^/logoff\.do$", re.IGNORECASE),
)


def read_only_enabled() -> bool:
    return os.environ.get("OV_READONLY", "").strip().lower() in {"1", "true", "yes", "on"}


def guard_read_only(method: str, path: str) -> None:
    if not read_only_enabled():
        return
    verb = method.upper()
    if verb in SAFE_METHODS:
        return
    cleaned = api_path(path).split("?", 1)[0]
    if verb == "POST" and any(rule.match(cleaned) for rule in READ_ONLY_POSTS):
        return
    raise ReadOnlyBlocked(
        f"Read-only mode (OV_READONLY) blocks {verb} {cleaned}. "
        "Only GET, searches, SQL test and component export are allowed."
    )


def guard_web_read_only(path: str) -> None:
    if not read_only_enabled():
        return
    raw = unquote(path.strip().split("?", 1)[0])
    cleaned = posixpath.normpath("/" + raw.lstrip("/"))
    allowed = ".." not in raw.split("/") and any(r.match(cleaned) for r in READ_ONLY_WEB_PATHS)
    if not allowed:
        raise ReadOnlyBlocked(f"Read-only mode (OV_READONLY) blocks web request {cleaned}.")


class Client:
    def __init__(
        self,
        session: Session,
        timeout: float = 60.0,
        verify: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.session = session
        self.base_url = session.base_url.rstrip("/")
        self.host = httpx.URL(self.base_url).host if self.base_url else ""
        self._http = httpx.Client(
            base_url=self.base_url,
            follow_redirects=True,
            timeout=timeout,
            verify=verify,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )
        # Without a domain the server's Set-Cookie adds a duplicate under the host.
        for name, value in session.cookies.items():
            self._http.cookies.set(name, value, domain=self.host, path="/")

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def api(
        self,
        method: str,
        path: str,
        params: list[tuple[str, str]] | None = None,
        json: Any = None,
        content: bytes | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        guard_read_only(method, path)
        if self.session.needs_refresh():
            self.refresh_token()

        response = self._send(method, path, params, json, content, files, headers, accept)
        if response.status_code == 401 and not self.session.is_static and self.session.cookies:
            self.refresh_token()
            response = self._send(method, path, params, json, content, files, headers, accept)

        return self._checked(response)

    def _send(
        self,
        method: str,
        path: str,
        params: list[tuple[str, str]] | None,
        json: Any,
        content: bytes | None,
        files: dict[str, Any] | None,
        headers: dict[str, str] | None,
        accept: str,
    ) -> httpx.Response:
        request_headers = {"Accept": accept}
        if self.session.bearer_token:
            request_headers["Authorization"] = f"Bearer {self.session.bearer_token}"
        request_headers.update(headers or {})

        with _reachable(self.base_url):
            return self._http.request(
                method.upper(),
                api_path(path),
                params=params,
                json=json,
                content=content,
                files=files,
                headers=request_headers,
            )

    # No Authorization header: the token chain rejects web-session tokens as the wrong type.
    def web_get(self, path: str, accept: str = "application/json") -> httpx.Response:
        guard_web_read_only(path)
        if self.session.is_static or not self.session.cookies:
            raise SessionExpired("no web session cookies stored")

        with _reachable(self.base_url):
            response = self._http.get(
                path,
                headers={"Accept": accept, "X-Requested-With": "XMLHttpRequest"},
            )
        if LOGIN_PATH.lower() in str(response.url).lower():
            raise SessionExpired("redirected to the login page")
        return self._checked(response)

    def tenants(self) -> dict[str, str]:
        if self.session.is_static or not self.session.cookies:
            raise SessionExpired("no web session cookies stored")
        return list_tenants(self._http)

    def refresh_token(self) -> None:
        if self.session.is_static:
            raise SessionExpired("the stored API token was rejected")
        if not self.session.cookies:
            raise SessionExpired("no web session cookies stored")
        mint_web_session_token(self._http, self.session)
        session_store.save(self.session)

    def _checked(self, response: httpx.Response) -> httpx.Response:
        if response.status_code < 400:
            return response

        detail = _detail(response)
        url = str(response.url)
        if response.status_code == 401:
            raise SessionExpired(detail or "the server rejected the token")
        if response.status_code == 403:
            raise Forbidden(detail or "Forbidden. The account lacks a privilege this call needs.")
        if response.status_code == 404:
            raise NotFound(detail or f"No such endpoint or record: {url}")
        raise ApiError(
            response.status_code, detail or f"HTTP {response.status_code}", _body(response), url
        )


# httpx transport errors are not OvError; unwrapped they end in a traceback, not an exit code.
@contextmanager
def _reachable(base_url: str) -> Iterator[None]:
    try:
        yield
    except httpx.TimeoutException as exc:
        raise Unreachable(
            f"{base_url} timed out. Raise timeout_seconds, or check the URL."
        ) from exc
    except httpx.RequestError as exc:
        raise Unreachable(f"Could not reach {base_url}: {exc}") from exc


def api_path(path: str) -> str:
    cleaned = "/" + path.strip().lstrip("/")
    if cleaned.startswith(f"{API_PREFIX}/"):
        return cleaned
    return f"{API_PREFIX}{cleaned}"


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:2000]


# API errors come back as text/plain unless a handler happened to answer with JSON.
def _detail(response: httpx.Response) -> str:
    content_type = (response.headers.get("content-type") or "").lower()
    if "json" in content_type:
        payload = _body(response)
        if isinstance(payload, dict):
            for key in ("message", "error", "detail", "description"):
                if payload.get(key):
                    return str(payload[key])
        return ""
    text = (response.text or "").strip()
    if not text or text.lstrip().startswith("<"):
        return ""
    return text[:1000]
