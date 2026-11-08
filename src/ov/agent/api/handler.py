from __future__ import annotations

import gzip
import json
import re
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

from ov.agent import providers
from ov.agent import workspace as project
from ov.agent.api import session
from ov.agent.api.screen import ScreenError
from ov.agent.engine.files import within
from ov.agent.engine.run_common import RunError
from ov.agent.integrations.datadog import DatadogError
from ov.agent.integrations.pagerduty import PagerDutyError
from ov.agent.skills import SkillError
from ov.browser.pilot import BrowserError
from ov.core.errors import OvError

STATIC_DIR = Path(__file__).parent.parent / "static"
DEV_PORT = 5179
LOOPBACK_HOST = "127.0.0.1"
LOCAL_HOSTS = (LOOPBACK_HOST, "localhost")
BYTES_PER_MB = 1024 * 1024
MAX_UPLOAD_MB = 50
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * BYTES_PER_MB
GZIP_MIN_BYTES = 64 * 1024
GZIP_LEVEL = 5
ASSET_CACHE = "public, max-age=31536000, immutable"
APP_ID = "ov-agent"
PUBLIC_API = ("/api/health",)
NOT_SIGNED_IN = "Open OV Agent from the link 'ov agent' prints."
SIGN_IN_PAGE = (
    b"<!doctype html><meta charset=utf-8><title>OV Agent</title>"
    b'<body style="font:15px system-ui;margin:15vh auto;max-width:28rem;color:#263238">'
    b'<h1 style="font-size:20px">Open OV Agent from your terminal</h1>'
    b"<p>This browser has not been signed in to the agent yet. Run <code>ov agent</code> again: it opens "
    b"the app here with a sign-in link, and this page then works as usual.</p>"
)

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
}

TRUSTED_FETCH_SITES = ("same-origin", "none")
_BODY_TYPES = ("application/json", "application/octet-stream")
CLIENT_ERRORS = (
    RunError,
    SkillError,
    project.ProjectError,
    *providers.errors(),
    DatadogError,
    PagerDutyError,
    ScreenError,
    BrowserError,
    OvError,
    ValueError,
)


class HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


Route = tuple[str, re.Pattern[str], Callable[..., Any]]
ROUTES: list[Route] = []


def route(method: str, pattern: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn

    return register


def required(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise HttpError(400, f"Missing {key}.")
    return value


def objects(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = data.get(key) or []
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise HttpError(400, f"{key} must be a list of objects.")
    return items


def strings(data: dict[str, Any], key: str) -> list[str]:
    items = data.get(key) or []
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise HttpError(400, f"{key} must be a list of strings.")
    return items


class Handler(BaseHTTPRequestHandler):
    server_version = APP_ID
    _unread = 0

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    @property
    def query(self) -> dict[str, str]:
        parsed = parse_qs(urlsplit(self.path).query)
        return {k: v[-1] for k, v in parsed.items()}

    def body(self) -> bytes:
        length = self._unread
        if length > MAX_UPLOAD_BYTES:
            raise HttpError(413, f"File is larger than {MAX_UPLOAD_MB}MB.")
        self._unread = 0
        return self.rfile.read(length) if length else b""

    def _drain(self) -> None:
        if self._unread > MAX_UPLOAD_BYTES:
            self.close_connection = True
        elif self._unread:
            self.rfile.read(self._unread)
        self._unread = 0

    def json(self) -> dict[str, Any]:
        raw = self.body()
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            raise HttpError(400, "Body is not JSON.") from None

        if not isinstance(data, dict):
            raise HttpError(400, "Body must be a JSON object.")
        return data

    def send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        cache: str = "no-store",
        extra: dict[str, str] | None = None,
    ) -> None:
        self._drain()

        if len(body) > GZIP_MIN_BYTES and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gzip.compress(body, compresslevel=GZIP_LEVEL)
            extra = {**(extra or {}), "Content-Encoding": "gzip"}

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra or {}).items():
            self.send_header(name, value)

        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: Any, status: int = 200) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.send(status, text.encode("utf-8"), "application/json")

    def _trusted(self, method: str) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in LOCAL_HOSTS:
            return False
        if self.headers.get("Sec-Fetch-Site", "none") not in TRUSTED_FETCH_SITES:
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in self._origins():
            return False

        if method in ("POST", "PUT"):
            content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return content_type in _BODY_TYPES
        return True

    def _signed_in(self) -> bool:
        return session.matches(session.from_cookies(self.headers.get("Cookie")), self.server.session_token)

    def _origins(self) -> set[str]:
        ports = (self.server.server_address[1], DEV_PORT)
        return {f"http://{host}:{port}" for host in LOCAL_HOSTS for port in ports}

    def _dispatch(self, method: str) -> None:
        self._unread = max(int(self.headers.get("Content-Length") or 0), 0)

        try:
            self._handle(method, urlsplit(self.path).path)
        except HttpError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except CLIENT_ERRORS as exc:
            self.send_json({"error": str(exc)}, 400)
        except httpx.HTTPError as exc:
            self.send_json({"error": f"Network error: {exc}"}, 502)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _handle(self, method: str, path: str) -> None:
        if not path.startswith("/api/"):
            self._static(path)
            return
        if not self._trusted(method):
            raise HttpError(403, "Forbidden.")
        if path not in PUBLIC_API and not self._signed_in():
            raise HttpError(401, NOT_SIGNED_IN)

        for verb, pattern, fn in ROUTES:
            match = pattern.match(path)
            if verb == method and match:
                result = fn(self, *(unquote(g) for g in match.groups()))
                if result is not None:
                    self.send_json(result)
                return

        raise HttpError(404, "Not found.")

    def _static(self, path: str) -> None:
        index = STATIC_DIR / "index.html"
        if not index.exists():
            raise HttpError(500, "The web UI is not built. Run 'pnpm build' in web/.")

        token = self.server.session_token
        if session.matches(self.query.get(session.LINK_PARAM), token):
            self.send(303, b"", "text/plain", extra={"Location": path, "Set-Cookie": session.set_cookie(token)})
            return

        rel = path.lstrip("/")
        target = within(STATIC_DIR, rel) if rel else index
        if not target.is_file():
            target = index
        if target == index and not self._signed_in():
            self.send(401, SIGN_IN_PAGE, CONTENT_TYPES[".html"])
            return

        cache = ASSET_CACHE if "/assets/" in path else "no-cache"
        content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send(200, target.read_bytes(), content_type, cache)
