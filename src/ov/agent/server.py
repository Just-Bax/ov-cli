from __future__ import annotations

import json
import queue
import random
import re
import string
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

import httpx

from .. import __version__
from ..errors import OvError
from . import copilot, db, skills, sources
from .copilot import CopilotError
from .ovproc import instances, login, version
from .run import RunError, runs
from .skills import SkillError
from .sources import SourceError
from .workspace import attachments_dir, uploads_dir, within

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 5180
DEV_PORT = 5179
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PING_SECONDS = 15
APP_ID = "ov-agent"

# Windows' mimetypes reads the registry, which often maps .js to text/plain.
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

INLINE_FILES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".log", ".csv"}
_BODY_TYPES = ("application/json", "application/octet-stream")


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


class Handler(BaseHTTPRequestHandler):
    server_version = APP_ID
    server: AgentServer

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
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            raise HttpError(413, "File is larger than 50MB.")
        return self.rfile.read(length) if length else b""

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

    # A browser tab on any site can reach 127.0.0.1, so only same-machine pages may call the
    # API, and bodies must use a type that forces a CORS preflight.
    def _trusted(self, method: str) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in self._origins():
            return False
        if method in ("POST", "PUT"):
            content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return content_type in _BODY_TYPES
        return True

    # Other local web apps must not drive the agent; the Vite dev server is the one exception.
    def _origins(self) -> set[str]:
        ports = (self.server.server_address[1], DEV_PORT)
        return {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in ports}

    def _dispatch(self, method: str) -> None:
        path = urlsplit(self.path).path
        try:
            if not path.startswith("/api/"):
                self._static(path)
                return
            if not self._trusted(method):
                raise HttpError(403, "Forbidden.")
            for verb, pattern, fn in ROUTES:
                match = pattern.match(path)
                if verb == method and match:
                    result = fn(self, *(unquote(g) for g in match.groups()))
                    if result is not None:
                        self.send_json(result)
                    return
            raise HttpError(404, "Not found.")
        except HttpError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except (RunError, SkillError, SourceError, CopilotError, OvError, ValueError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except httpx.HTTPError as exc:
            self.send_json({"error": f"Network error: {exc}"}, 502)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:
            self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _static(self, path: str) -> None:
        index = STATIC_DIR / "index.html"
        if not index.exists():
            raise HttpError(500, "The web UI is not built. Run 'pnpm build' in web/.")
        rel = path.lstrip("/")
        target = within(STATIC_DIR, rel) if rel else index
        if not target.is_file():
            target = index
        cache = "public, max-age=31536000, immutable" if "/assets/" in path else "no-cache"
        content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send(200, target.read_bytes(), content_type, cache)


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second server bind the same port silently.
    allow_reuse_address = sys.platform != "win32"


def _run(run_id: str) -> Any:
    run = runs.get(run_id)
    if run is None:
        raise HttpError(404, "Run not found.")
    return run


def _short_id() -> str:
    stamp = f"{int(time.time() * 1000):x}"
    return stamp + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))


@route("GET", "/api/health")
def health(_: Handler) -> dict[str, Any]:
    return {"app": APP_ID, "version": __version__}


@route("GET", "/api/status")
def status(_: Handler) -> dict[str, Any]:
    user = copilot.user()
    rows = instances()
    settings = db.get_settings()
    return {
        "copilot": {"signedIn": bool(user), "user": user},
        "ov": {"version": version()},
        "instances": {"total": len(rows), "valid": sum(1 for r in rows if r["valid"])},
        "settings": settings,
        "ready": bool(user and rows and settings["defaultModel"]),
    }


@route("POST", "/api/copilot/device")
def copilot_device(_: Handler) -> dict[str, Any]:
    return copilot.start_device_flow()


@route("POST", "/api/copilot/poll")
def copilot_poll(h: Handler) -> dict[str, Any]:
    return copilot.poll_device_flow(str(h.json().get("deviceCode", "")))


@route("POST", "/api/copilot/logout")
def copilot_logout(_: Handler) -> dict[str, Any]:
    copilot.sign_out()
    return {"ok": True}


@route("GET", "/api/models")
def models(_: Handler) -> list[dict[str, Any]]:
    return copilot.list_models()


@route("GET", "/api/instances")
def list_instances(_: Handler) -> list[dict[str, Any]]:
    return instances()


@route("POST", "/api/instances/login")
def login_instance(h: Handler) -> dict[str, Any]:
    url = str(h.json().get("url", "")).strip()
    if not url:
        raise HttpError(400, "Give an instance URL.")
    result = login(url)
    return {"ok": result.code == 0, "message": result.message[-400:]}


@route("GET", "/api/settings")
def get_settings(_: Handler) -> dict[str, Any]:
    return db.get_settings()


@route("PUT", "/api/settings")
def put_settings(h: Handler) -> dict[str, Any]:
    return db.save_settings(h.json())


@route("GET", "/api/skills")
def list_skills(_: Handler) -> list[dict[str, Any]]:
    return skills.list_skills()


@route("POST", "/api/skills")
def create_skill(h: Handler) -> dict[str, Any]:
    data = h.json()
    name = skills.create(
        str(data.get("title", "")), str(data.get("description", "")), str(data.get("content", ""))
    )
    return {"name": name, "skills": skills.list_skills()}


@route("PUT", "/api/skills/([^/]+)")
def update_skill(h: Handler, name: str) -> list[dict[str, Any]]:
    skills.update(name, h.json())
    return skills.list_skills()


@route("DELETE", "/api/skills/([^/]+)")
def delete_skill(_: Handler, name: str) -> list[dict[str, Any]]:
    skills.delete(name)
    return skills.list_skills()


@route("GET", "/api/sources")
def list_sources(_: Handler) -> list[dict[str, Any]]:
    return sources.list_sources()


@route("POST", "/api/sources")
def add_source(h: Handler) -> list[dict[str, Any]]:
    data = h.json()
    sources.add(
        str(data.get("name", "")), str(data.get("description", "")), str(data.get("location", ""))
    )
    return sources.list_sources()


@route("PUT", "/api/sources/([^/]+)")
def update_source(h: Handler, name: str) -> list[dict[str, Any]]:
    data = h.json()
    sources.update(name, str(data.get("description", "")), str(data.get("location", "")))
    return sources.list_sources()


@route("POST", "/api/sources/([^/]+)/sync")
def sync_source(_: Handler, name: str) -> list[dict[str, Any]]:
    sources.sync(name)
    return sources.list_sources()


@route("DELETE", "/api/sources/([^/]+)")
def delete_source(_: Handler, name: str) -> list[dict[str, Any]]:
    sources.remove(name)
    return sources.list_sources()


@route("POST", "/api/uploads")
def upload(h: Handler) -> dict[str, str]:
    name = unquote(h.headers.get("X-File-Name") or "file")
    upload_id = _short_id()
    (uploads_dir() / upload_id).write_bytes(h.body())
    return {"id": upload_id, "name": Path(name).name or "file"}


@route("GET", "/api/runs")
def list_runs(_: Handler) -> list[dict[str, Any]]:
    return db.list_runs()


@route("GET", "/api/stats")
def stats(_: Handler) -> dict[str, Any]:
    now = db.now_ms()
    day = 86_400_000
    return {
        "week": db.saved_totals(now - 7 * day),
        "month": db.saved_totals(now - 30 * day),
        "all": db.saved_totals(0),
    }


@route("POST", "/api/runs")
def start_run(h: Handler) -> dict[str, str]:
    data = h.json()
    settings = db.get_settings()
    prompt = str(data.get("prompt") or "").strip()
    attachments = [a for a in data.get("attachments") or [] if isinstance(a, dict)]
    if not prompt and not attachments:
        raise HttpError(400, "Describe what you need.")
    model = str(data.get("model") or settings["defaultModel"])
    if not model:
        raise HttpError(400, "Pick a model first (Settings).")

    instance = str(data.get("instance") or settings["defaultInstance"] or "")
    if not instance:
        instance = next((i["alias"] for i in instances() if i["current"]), "")
    run = runs.create(
        {
            "prompt": prompt,
            "instance": instance or None,
            "attachments": attachments,
            "allowWrite": bool(data.get("allowWrite")),
        },
        model,
    )
    return {"id": run.id}


@route("GET", "/api/runs/([a-z0-9]+)")
def get_run(_: Handler, run_id: str) -> str:
    return _run(run_id).snapshot()


@route("DELETE", "/api/runs/([a-z0-9]+)")
def delete_run(_: Handler, run_id: str) -> dict[str, bool]:
    _run(run_id)
    runs.delete(run_id)
    return {"ok": True}


@route("GET", "/api/runs/([a-z0-9]+)/events")
def run_events(h: Handler, run_id: str) -> None:
    run = _run(run_id)
    last = int(h.query.get("after", "-1"))
    channel, unsubscribe = run.subscribe()
    try:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.end_headers()
        for stored in db.load_events(run.id, last):
            _write_event(h, stored)
            last = stored["seq"]
        while True:
            try:
                stored = channel.get(timeout=PING_SECONDS)
            except queue.Empty:
                h.wfile.write(b"event: ping\ndata: \n\n")
                h.wfile.flush()
                continue
            if stored["seq"] > last:
                _write_event(h, stored)
                last = stored["seq"]
    except OSError:
        pass
    finally:
        unsubscribe()


def _write_event(h: Handler, stored: dict[str, Any]) -> None:
    h.wfile.write(f"id: {stored['seq']}\ndata: {json.dumps(stored)}\n\n".encode())
    h.wfile.flush()


@route("POST", "/api/runs/([a-z0-9]+)/answer")
def answer(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    _run(run_id).answer(str(data.get("questionId", "")), str(data.get("answer", "")))
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/login")
def run_login(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    run = _run(run_id)
    threading.Thread(
        target=_quietly,
        args=(run.login, str(data.get("loginId", "")), bool(data.get("skip"))),
        daemon=True,
    ).start()
    return {"ok": True}


def _quietly(fn: Callable[..., Any], *args: Any) -> None:
    try:
        fn(*args)
    except Exception:
        pass


@route("POST", "/api/runs/([a-z0-9]+)/message")
def message(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    files = [f for f in data.get("files") or [] if isinstance(f, dict)]
    _run(run_id).follow_up(str(data.get("text", "")), files)
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/retry")
def retry(h: Handler, run_id: str) -> dict[str, bool]:
    _run(run_id).retry(str(h.json().get("itemId", "")))
    return {"ok": True}


@route("DELETE", "/api/runs/([a-z0-9]+)/queued/([^/]+)")
def remove_queued(_: Handler, run_id: str, message_id: str) -> dict[str, bool]:
    _run(run_id).remove_queued(message_id)
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/rate")
def rate(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    _run(run_id).rate(str(data.get("turnId", "")), data.get("rating"), data.get("note"))
    return {"ok": True}


@route("GET", "/api/runs/([a-z0-9]+)/files/([^/]+)")
def run_file(h: Handler, run_id: str, name: str) -> None:
    _run(run_id)
    path = within(attachments_dir(run_id), Path(name).name)
    if not path.is_file():
        raise HttpError(404, "File not found.")
    # Same origin as the API, so anything that could run script (html, svg) is downloaded.
    suffix = path.suffix.lower()
    if suffix in INLINE_FILES:
        content_type, disposition = CONTENT_TYPES[suffix], "inline"
    else:
        content_type, disposition = "application/octet-stream", "attachment"
    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(path.name)}"}
    # Chrome refuses to show a sandboxed PDF; its viewer does not run scripts in our origin.
    if suffix != ".pdf":
        headers["Content-Security-Policy"] = "sandbox"
    h.send(200, path.read_bytes(), content_type, extra=headers)


@route("POST", "/api/runs/([a-z0-9]+)/access")
def access(h: Handler, run_id: str) -> dict[str, bool]:
    _run(run_id).set_write_access(bool(h.json().get("write")))
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/cancel")
def cancel(_: Handler, run_id: str) -> dict[str, bool]:
    _run(run_id).stop()
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/feedback")
def feedback(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    rating, note = str(data.get("rating", "")), str(data.get("note") or "")
    if rating not in ("good", "off", "wrong"):
        raise HttpError(400, "Unknown rating.")
    run = _run(run_id)
    db.save_feedback(run_id, rating, note)
    run.state["feedback"] = {"rating": rating, "note": note}
    return {"ok": True}


def already_running(port: int) -> bool:
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2)
        return response.json().get("app") == APP_ID
    except (httpx.HTTPError, ValueError):
        return False


def serve(port: int = DEFAULT_PORT, open_browser: bool = True) -> int:
    url = f"http://127.0.0.1:{port}"
    try:
        server = AgentServer(("127.0.0.1", port), Handler)
    except OSError:
        if not already_running(port):
            raise OvError(f"Port {port} is in use by another program. Pass --port.") from None
        print(f"OV Agent is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return 0

    print(f"OV Agent running at {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        db.close()
    return 0
