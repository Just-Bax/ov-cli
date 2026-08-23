from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from . import API_PREFIX
from . import session as session_store
from .auth import LOGIN_PATH, mint_web_session_token
from .errors import ApiError, Forbidden, NotFound, SessionExpired, Unreachable
from .session import Session

USER_AGENT = "ov-cli"


class Client:
    """HTTP access to one OneVizion instance as one user.

    Two doors into the same server, and they must not be confused: /api/** is
    reached with the bearer token and rejects cookies, while the OpenAPI schema
    and the token-minting endpoint are served by the web UI chain, which reads
    cookies and refuses a request carrying an Authorization header.
    """

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
        # Seeded without a domain these land under "", and the server's own
        # Set-Cookie then adds a second entry under the host, leaving two
        # cookies of the same name in the jar.
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
        """Call an /api endpoint with the bearer token, refreshing it if the
        server says it is no longer good."""
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

    def web_get(self, path: str, accept: str = "application/json") -> httpx.Response:
        """Fetch a web UI URL with cookies only.

        No Authorization header: adding one would route the request to the
        stateless token chain, which rejects a web-session token as the wrong
        type instead of serving the page.
        """
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


@contextmanager
def _reachable(base_url: str) -> Iterator[None]:
    """Turn a transport failure into a reportable error.

    Without this a VPN-only instance, a typo in a URL or an expired certificate
    ends the process in an httpx traceback rather than a message and an exit
    code.
    """
    try:
        yield
    except httpx.TimeoutException as exc:
        raise Unreachable(
            f"{base_url} timed out. Raise timeout_seconds, or check the URL."
        ) from exc
    except httpx.RequestError as exc:
        raise Unreachable(f"Could not reach {base_url}: {exc}") from exc


def api_path(path: str) -> str:
    """Accept '/v3/users', 'v3/users' and '/api/v3/users' as the same thing."""
    cleaned = "/" + path.strip().lstrip("/")
    if cleaned.startswith(f"{API_PREFIX}/"):
        return cleaned
    return f"{API_PREFIX}{cleaned}"


def _body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:2000]


def _detail(response: httpx.Response) -> str:
    """API errors come back as text/plain, so the body is the message itself
    unless a handler happened to answer with JSON."""
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
