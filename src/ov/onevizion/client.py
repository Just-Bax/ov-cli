from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qsl, unquote

import httpx

from ov import API_PREFIX
from ov.core.config import TRUE_WORDS
from ov.core.errors import ApiError, Forbidden, NotFound, OvError, ReadOnlyBlocked, SessionExpired, Unreachable
from ov.onevizion import session as session_store
from ov.onevizion.auth import (
    LOGIN_PATH,
    csrf_headers,
    list_tenants,
    mint_web_session_token,
    server_message,
)
from ov.onevizion.session import Session
from ov.onevizion.tenants import DEFAULT_PATH

USER_AGENT = "ov-cli"
READ_ONLY_ENV = "OV_READONLY"
DEFAULT_TIMEOUT_SECONDS = 60.0
ERROR_BODY_LIMIT = 2000

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

READ_ONLY_POSTS = (
    re.compile(r"^/api/v3/trackor_types/[^/]+/trackors/search$"),
    re.compile(r"^/api/v3/sql/test$"),
    re.compile(r"^/api/v3/components/exports/run$"),
)

DRY_RUN_POSTS = (re.compile(r"^/api/v3/components/imports/run$"),)
DRY_RUN_PARAM = "is_dry_run"

READ_ONLY_WEB_PATHS = (
    re.compile(r"^/api/docs/"),
    re.compile(r"^/logoff\.do$", re.IGNORECASE),
)


def read_only_enabled() -> bool:
    return os.environ.get(READ_ONLY_ENV, "").strip().lower() in TRUE_WORDS


def _dry_run(path: str, params: list[tuple[str, str]]) -> bool:
    query = parse_qsl(api_path(path).partition("?")[2])
    values = [value for name, value in [*query, *params] if name == DRY_RUN_PARAM]
    return len(values) == 1 and values[0].lower() in TRUE_WORDS


def guard_read_only(method: str, path: str, params: list[tuple[str, str]] | None = None) -> None:
    if not read_only_enabled():
        return

    verb = method.upper()
    if verb in SAFE_METHODS:
        return

    cleaned = api_path(path).split("?", 1)[0]
    if verb == "POST" and any(rule.match(cleaned) for rule in READ_ONLY_POSTS):
        return
    if verb == "POST" and any(rule.match(cleaned) for rule in DRY_RUN_POSTS) and _dry_run(path, params or []):
        return

    raise ReadOnlyBlocked(
        f"Read-only mode ({READ_ONLY_ENV}) blocks {verb} {cleaned}. "
        "Only GET, searches, SQL test, component export and component import dry runs are allowed."
    )


def guard_web_read_only(path: str) -> None:
    if not read_only_enabled():
        return

    raw = unquote(path.strip().split("?", 1)[0])
    cleaned = posixpath.normpath("/" + raw.lstrip("/"))
    allowed = ".." not in raw.split("/") and any(r.match(cleaned) for r in READ_ONLY_WEB_PATHS)
    if not allowed:
        raise ReadOnlyBlocked(f"Read-only mode ({READ_ONLY_ENV}) blocks web request {cleaned}.")


class Client:
    def __init__(
        self,
        session: Session,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        verify: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.session = session
        self.base_url = session.base_url.rstrip("/")
        self.host = httpx.URL(self.base_url).host
        self._http = httpx.Client(
            base_url=self.base_url,
            follow_redirects=True,
            timeout=timeout,
            verify=verify,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )

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
        *,
        params: list[tuple[str, str]] | None = None,
        json: Any = None,
        content: bytes | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        guard_read_only(method, path, params)

        if self.session.needs_refresh():
            self.refresh_token()

        request = {"params": params, "json": json, "content": content, "files": files}
        response = self._send(method, path, request, headers, accept)
        if response.status_code == 401 and not self.session.is_static and self.session.cookies:
            self.refresh_token()
            response = self._send(method, path, request, headers, accept)

        return self._checked(response)

    def _send(
        self,
        method: str,
        path: str,
        request: dict[str, Any],
        headers: dict[str, str] | None,
        accept: str,
    ) -> httpx.Response:
        request_headers = {"Accept": accept}
        if self.session.bearer_token:
            request_headers["Authorization"] = f"Bearer {self.session.bearer_token}"

        if headers:
            request_headers.update(headers)

        with _reachable(self.base_url):
            return self._http.request(method.upper(), api_path(path), headers=request_headers, **request)

    def web_get(self, path: str, accept: str = "application/json") -> httpx.Response:
        guard_web_read_only(path)

        if not self.session.cookies:
            raise SessionExpired("no web session cookies stored")

        with _reachable(self.base_url):
            response = self._http.get(path, headers={"Accept": accept, "X-Requested-With": "XMLHttpRequest"})
        if LOGIN_PATH.lower() in str(response.url).lower():
            raise SessionExpired("redirected to the login page")
        return self._checked(response)

    def web_post_form(self, path: str, data: dict[str, str], timeout: float) -> httpx.Response:
        guard_web_read_only(path)
        if not self.session.cookies:
            raise SessionExpired("no web session cookies stored")

        with _reachable(self.base_url):
            headers = {**csrf_headers(self._http), "Accept": "*/*"}
            response = self._http.post(path, data=data, headers=headers, timeout=timeout)
        if LOGIN_PATH.lower() in str(response.url).lower() or response.status_code == httpx.codes.UNAUTHORIZED:
            raise SessionExpired("the web session was not accepted")
        return self._checked(response)

    def web_session_alive(self) -> bool:
        if not self.session.cookies:
            return False

        with _reachable(self.base_url):
            response = self._http.get(DEFAULT_PATH, headers={"Accept": "text/html"}, follow_redirects=False)
        return response.status_code == httpx.codes.OK and LOGIN_PATH.lower() not in response.text.lower()

    def post_json(self, path: str, payload: Any) -> httpx.Response:
        if self.session.needs_refresh():
            self.refresh_token()

        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.session.bearer_token}"}
        with _reachable(self.base_url):
            response = self._http.post(path, json=payload, headers=headers)
        if response.status_code == 401 and not self.session.is_static and self.session.cookies:
            self.refresh_token()
            headers["Authorization"] = f"Bearer {self.session.bearer_token}"
            with _reachable(self.base_url):
                response = self._http.post(path, json=payload, headers=headers)

        return self._checked(response)

    def tenants(self) -> dict[str, str]:
        self._require_web_session()
        return list_tenants(self._http)

    def refresh_token(self) -> None:
        if self.session.is_static:
            session_store.mark_ended(self.session)
            raise SessionExpired("the stored API token was rejected")

        self._require_web_session()
        try:
            mint_web_session_token(self._http, self.session)
        except SessionExpired:
            session_store.mark_ended(self.session)
            raise

        session_store.save(self.session)

    def _require_web_session(self) -> None:
        if self.session.is_static or not self.session.cookies:
            raise SessionExpired("no web session cookies stored")

    def _checked(self, response: httpx.Response) -> httpx.Response:
        if response.status_code < 400:
            return response

        detail = _detail(response)
        url = str(response.url)
        if response.status_code == 401:
            if self.session.is_static:
                session_store.mark_ended(self.session)
            raise SessionExpired(detail or "the server rejected the token")
        if response.status_code == 403:
            raise Forbidden(detail or "Forbidden. The account lacks a privilege this call needs.")
        if response.status_code == 404:
            raise NotFound(detail or f"No such endpoint or record: {url}")
        raise ApiError(response.status_code, detail or f"HTTP {response.status_code}", _body(response), url)


@contextmanager
def _reachable(base_url: str) -> Iterator[None]:
    try:
        yield
    except httpx.TimeoutException as exc:
        raise Unreachable(f"{base_url} timed out. Raise timeout_seconds, or check the URL.") from exc
    except httpx.RequestError as exc:
        raise Unreachable(f"Could not reach {base_url}: {exc}") from exc


def api_path(path: str) -> str:
    cleaned = "/" + path.strip().lstrip("/")
    if ".." in unquote(cleaned.split("?", 1)[0]).split("/"):
        raise OvError(f"API paths cannot step out of {API_PREFIX} with '..': {path}")
    if cleaned.startswith(f"{API_PREFIX}/"):
        return cleaned
    return f"{API_PREFIX}{cleaned}"


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:ERROR_BODY_LIMIT]


def _detail(response: httpx.Response) -> str:
    return server_message(response.text)
