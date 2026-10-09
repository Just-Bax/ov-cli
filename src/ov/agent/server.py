from __future__ import annotations

import gzip
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
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

import httpx

from .. import __version__
from ..errors import OvError
from . import copilot, datadog, db, explorer, graph, pagerduty, project, skills
from .cancel import Cancel
from .copilot import CopilotError
from .datadog import DatadogError
from .explorer import ExplorerError
from .ovproc import instances, login, run_ov, version
from .pagerduty import PagerDutyError
from .run import RunError, runs, status_feed
from .runfiles import attachments_dir, uploads_dir, within
from .screen import ScreenError, find_screen, screen_key
from .skills import SkillError

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_PORT = 5180
DEV_PORT = 5179
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
GZIP_MIN_BYTES = 64 * 1024
PING_SECONDS = 15
SETTLED_PAGE = 50
DEFAULT_TURNS = 10
MAX_TURNS = 100
GZIP_LEVEL = 5
ASSET_CACHE = "public, max-age=31536000, immutable"
UPLOAD_ID_SUFFIX_CHARS = 6
LOGOUT_TIMEOUT_SECONDS = 60
LOGOUT_MESSAGE_CHARS = 300
LOGIN_MESSAGE_CHARS = 400
HEALTH_CHECK_TIMEOUT_SECONDS = 2
DEFAULT_RANGE = "24h"
DAY_MS = 86_400_000
SECONDS_PER_DAY = 86_400
FAILED_PROCESS_STATUSES = "3, 14, 21"
FAILED_PROCESS_TYPES_SHOWN = 20
APP_ID = "ov-agent"
SCREEN_APPEAR_SECONDS = 10
SCREEN_APPEAR_POLL_SECONDS = 0.2

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
CLIENT_ERRORS = (
    RunError,
    SkillError,
    project.ProjectError,
    CopilotError,
    ExplorerError,
    DatadogError,
    PagerDutyError,
    ScreenError,
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


class Handler(BaseHTTPRequestHandler):
    server_version = APP_ID
    server: AgentServer
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
            raise HttpError(413, "File is larger than 50MB.")
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
        if host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in self._origins():
            return False
        if method in ("POST", "PUT"):
            content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return content_type in _BODY_TYPES
        return True

    def _origins(self) -> set[str]:
        ports = (self.server.server_address[1], DEV_PORT)
        return {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in ports}

    def _dispatch(self, method: str) -> None:
        self._unread = int(self.headers.get("Content-Length") or 0)
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

        rel = path.lstrip("/")
        target = within(STATIC_DIR, rel) if rel else index
        if not target.is_file():
            target = index
        cache = ASSET_CACHE if "/assets/" in path else "no-cache"
        content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send(200, target.read_bytes(), content_type, cache)


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"


def _run(run_id: str) -> Any:
    run = runs.get(run_id)
    if run is None:
        raise HttpError(404, "Run not found.")
    return run


def _required(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise HttpError(400, f"Missing {key}.")
    return value


def _objects(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = data.get(key) or []
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise HttpError(400, f"{key} must be a list of objects.")
    return items


def _short_id() -> str:
    stamp = f"{int(time.time() * 1000):x}"
    return stamp + "".join(random.choices(string.ascii_lowercase + string.digits, k=UPLOAD_ID_SUFFIX_CHARS))


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
    return copilot.poll_device_flow(_required(h.json(), "deviceCode"))


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
    data = h.json()
    url = str(data.get("url", "")).strip()
    if not url:
        raise HttpError(400, "Give an instance URL.")
    tenant = str(data.get("tenant") or "").strip()
    token = str(data.get("token") or "").strip()
    if token and tenant:
        raise HttpError(400, "An API token is tied to its own tenant; leave the tenant out.")

    screen = data.get("screen")
    size = (int(screen["width"]), int(screen["height"])) if screen else None
    result = login(url, tenant, token, size)
    return {"ok": result.code == 0, "message": result.message[-LOGIN_MESSAGE_CHARS:]}


@route("POST", "/api/instances/logout")
def logout_instance(h: Handler) -> list[dict[str, Any]]:
    alias = _instance_alias(h, _required(h.json(), "alias"))
    result = run_ov(["logout", alias, "--json"], timeout=LOGOUT_TIMEOUT_SECONDS, read_only=False)
    if result.code != 0:
        raise HttpError(400, result.message[-LOGOUT_MESSAGE_CHARS:] or "Could not remove the instance.")
    return instances()


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
    name = skills.create(str(data.get("title", "")), str(data.get("description", "")), str(data.get("content", "")))
    return {"name": name, "skills": skills.list_skills()}


@route("PUT", "/api/skills/([^/]+)")
def update_skill(h: Handler, name: str) -> list[dict[str, Any]]:
    skills.update(name, h.json())
    return skills.list_skills()


@route("DELETE", "/api/skills/([^/]+)")
def delete_skill(_: Handler, name: str) -> list[dict[str, Any]]:
    skills.delete(name)
    return skills.list_skills()


@route("GET", "/api/workspace/entries")
def workspace_entries(h: Handler) -> dict[str, Any]:
    return {"root": str(project.root()), "entries": project.entries(h.query.get("path", ""))}


@route("GET", "/api/workspace/file")
def workspace_file(h: Handler) -> dict[str, str]:
    path = _required(h.query, "path")
    return {"path": path, "content": project.text_of(path)}


@route("PUT", "/api/workspace/file")
def workspace_save(h: Handler) -> dict[str, str]:
    data = h.json()
    path = _required(data, "path")
    if not isinstance(data.get("content"), str):
        raise HttpError(400, "Give the file content as a string.")

    project.write(path, data["content"])
    return {"path": path, "content": project.text_of(path)}


@route("POST", "/api/uploads")
def upload(h: Handler) -> dict[str, str]:
    name = Path(unquote(h.headers.get("X-File-Name") or "")).name
    if not name:
        raise HttpError(400, "Give the file name in the X-File-Name header.")

    upload_id = _short_id()
    (uploads_dir() / upload_id).write_bytes(h.body())
    return {"id": upload_id, "name": name}


def _instance_alias(h: Handler, ref: str | None = None) -> str:
    ref = (h.query.get("instance", "") if ref is None else ref).strip()
    found = next((i for i in instances() if i["alias"] == ref), None)
    if found is None:
        raise HttpError(404, f"Unknown instance: {ref}")
    return found["alias"]


@route("GET", "/api/graph/status")
def graph_status(h: Handler) -> dict[str, Any]:
    return graph.status(_instance_alias(h))


@route("POST", "/api/graph/build")
def graph_build(h: Handler) -> dict[str, Any]:
    alias = _instance_alias(h, _required(h.json(), "instance"))
    explorer.forget(alias)
    return graph.start_build(alias)


@route("GET", "/api/graph")
def graph_get(h: Handler) -> str:
    path = graph.graph_file(_instance_alias(h))
    if not path.is_file():
        raise HttpError(404, "No map built for this instance yet.")
    return path.read_text(encoding="utf-8")


@route("GET", "/api/explorer/source")
def explorer_source(h: Handler) -> dict[str, Any]:
    return explorer.source(_instance_alias(h), h.query.get("id", ""))


@route("GET", "/api/explorer/activity")
def explorer_activity(h: Handler) -> list[dict[str, Any]]:
    return explorer.activity(_instance_alias(h), h.query.get("id", ""))


@route("GET", "/api/datadog")
def datadog_status(_: Handler) -> dict[str, Any]:
    return datadog.status()


@route("POST", "/api/datadog/connect")
def datadog_connect(h: Handler) -> dict[str, Any]:
    data = h.json()
    return datadog.connect(str(data.get("site") or ""), str(data.get("apiKey") or ""), str(data.get("appKey") or ""))


@route("POST", "/api/datadog/test")
def datadog_test(_: Handler) -> dict[str, Any]:
    return datadog.retest()


@route("DELETE", "/api/datadog")
def datadog_disconnect(_: Handler) -> dict[str, Any]:
    return datadog.disconnect()


@route("GET", "/api/datadog/discover")
def datadog_discover(_: Handler) -> dict[str, Any]:
    return datadog.discover()


@route("PUT", "/api/datadog/matches")
def datadog_matches(h: Handler) -> dict[str, Any]:
    matches = h.json().get("matches")
    if not isinstance(matches, dict):
        raise HttpError(400, "Give matches as an object of instance alias to Datadog filter.")
    return datadog.save_matches({str(k): str(v) for k, v in matches.items()})


FAILURE_TIMES_SHOWN = 500
UTC_OFFSET_SQL = "select round((sysdate - cast(sys_extract_utc(systimestamp) as date)) * 1440) m from dual"


def _failed_runs(alias: str, start: int, end: int) -> dict[str, Any]:
    sql = graph.SqlReader(alias, Cancel())
    days = round((end - start) / 1000 / SECONDS_PER_DAY, 4)
    failed = (
        "from process p join process_type t on t.process_type_id = p.process_type_id "
        f"where p.status_id in ({FAILED_PROCESS_STATUSES}) and p.submission_date > sysdate - {days}"
    )
    queries = {
        "byType": (
            "select t.process_type, count(*) n, to_char(max(p.submission_date), 'YYYY-MM-DD HH24:MI') last_at "
            f"{failed} group by t.process_type order by n desc",
            FAILED_PROCESS_TYPES_SHOWN,
        ),
        "times": (
            f"select t.process_type, to_char(p.submission_date, 'YYYY-MM-DD\"T\"HH24:MI:SS') at {failed} "
            "order by p.submission_date desc",
            FAILURE_TIMES_SHOWN,
        ),
        "offset": (UTC_OFFSET_SQL, 1),
    }
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = {name: pool.submit(sql.page, query, 0, size) for name, (query, size) in queries.items()}
        found = {name: future.result() for name, future in futures.items()}

    by_type, times = found["byType"], found["times"]
    offset = int(found["offset"][0]["M"])

    return {
        "byType": [{"type": r["PROCESS_TYPE"], "count": int(r["N"]), "last": r["LAST_AT"]} for r in by_type],
        "failures": [{"type": r["PROCESS_TYPE"], "at": r["AT"]} for r in times],
        "utcOffsetMinutes": offset,
    }


def _incidents(alias: str, start: int, end: int, range_key: str) -> dict[str, Any]:
    report = pagerduty.health(alias, start, end, range_key)
    if report is None:
        raise datadog.Unavailable("PagerDuty is not connected.")
    return report


def _health_range(h: Handler) -> str:
    range_key = h.query.get("range", DEFAULT_RANGE)
    if range_key not in datadog.RANGES:
        raise HttpError(400, f"Unknown range: {range_key}")
    return range_key


@route("GET", "/api/instance-health/meta")
def instance_health_meta(h: Handler) -> dict[str, Any]:
    return datadog.health_meta(_instance_alias(h), _health_range(h))


@route("GET", "/api/instance-health/([a-z]+)")
def instance_health_section(h: Handler, section: str) -> dict[str, Any]:
    alias = _instance_alias(h)
    range_key = _health_range(h)
    end = int(_required(h.query, "to"))
    start, _ = datadog.window(range_key, end)

    try:
        if section == "onevizion":
            return _failed_runs(alias, start, end)
        if section == "incidents":
            return _incidents(alias, start, end, range_key)
        return datadog.health_section(alias, range_key, section, end)
    except (datadog.Unavailable, graph.NoAccess) as exc:
        return {"unavailable": str(exc)}


@route("GET", "/api/pagerduty/incidents/([A-Za-z0-9]+)")
def pagerduty_incident_detail(_: Handler, ident: str) -> dict[str, Any]:
    return pagerduty.public(pagerduty.incident_detail(ident))


@route("GET", "/api/pagerduty")
def pagerduty_status(_: Handler) -> dict[str, Any]:
    return pagerduty.status()


@route("POST", "/api/pagerduty/connect")
def pagerduty_connect(h: Handler) -> dict[str, Any]:
    data = h.json()
    return pagerduty.connect(str(data.get("account") or ""), str(data.get("apiKey") or ""))


@route("POST", "/api/pagerduty/test")
def pagerduty_test(_: Handler) -> dict[str, Any]:
    return pagerduty.retest()


@route("DELETE", "/api/pagerduty")
def pagerduty_disconnect(_: Handler) -> dict[str, Any]:
    return pagerduty.disconnect()


@route("GET", "/api/runs")
def list_runs(h: Handler) -> dict[str, Any]:
    settled = min(int(h.query.get("settled", str(SETTLED_PAGE))), db.RUN_LIST_LIMIT)
    return {
        "active": db.list_runs(settled=False),
        "settled": db.list_runs(settled=True, limit=settled),
        "settledTotal": db.settled_count(),
    }


@route("GET", "/api/stats")
def stats(_: Handler) -> dict[str, Any]:
    now = db.now_ms()
    return {
        "week": db.saved_totals(now - 7 * DAY_MS),
        "month": db.saved_totals(now - 30 * DAY_MS),
        "all": db.saved_totals(0),
    }


@route("POST", "/api/runs")
def start_run(h: Handler) -> dict[str, str]:
    data = h.json()
    settings = db.get_settings()
    prompt = str(data.get("prompt") or "").strip()
    attachments = _objects(data, "attachments")
    if not prompt and not attachments:
        raise HttpError(400, "Describe what you need.")
    model = str(data.get("model") or settings["defaultModel"])
    if not model:
        raise HttpError(400, "Pick a model first (Settings).")

    instance = str(data.get("instance") or "").strip()
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
def get_run(h: Handler, run_id: str) -> str:
    return _run(run_id).snapshot(_turns(h))


def _turns(h: Handler) -> int:
    return max(1, min(int(h.query.get("turns", str(DEFAULT_TURNS))), MAX_TURNS))


@route("GET", "/api/runs/([a-z0-9]+)/history")
def run_history(h: Handler, run_id: str) -> str:
    return _run(run_id).history(int(_required(h.query, "end")), _turns(h))


@route("GET", "/api/runs/([a-z0-9]+)/details")
def run_details(h: Handler, run_id: str) -> str:
    tools = {x for x in h.query.get("tools", "").split(",") if x}
    edits = {x for x in h.query.get("edits", "").split(",") if x}
    return _run(run_id).details(tools, edits)


@route("POST", "/api/runs/([a-z0-9]+)/settle")
def settle(h: Handler, run_id: str) -> dict[str, bool]:
    _run(run_id)
    settled = h.json().get("settled")
    if not isinstance(settled, bool):
        raise HttpError(400, "Give settled as true or false.")

    db.set_settled(run_id, settled)
    status_feed.publish({"kind": "list"})
    return {"ok": True}


@route("GET", "/api/status-events")
def status_events(h: Handler) -> None:
    channel, unsubscribe = status_feed.subscribe()
    try:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.end_headers()
        while True:
            try:
                change = channel.get(timeout=PING_SECONDS)
            except queue.Empty:
                h.wfile.write(b"event: ping\ndata: \n\n")
                h.wfile.flush()
                continue
            h.wfile.write(f"data: {json.dumps(change)}\n\n".encode())
            h.wfile.flush()
    except OSError:
        pass
    finally:
        unsubscribe()


def _screen_of(h: Handler) -> Any:
    key = screen_key(_required(h.query, "url"), h.query.get("tenant", ""))
    deadline = time.monotonic() + SCREEN_APPEAR_SECONDS
    while (screen := find_screen(key)) is None:
        if time.monotonic() > deadline:
            raise HttpError(404, "No sign-in browser is open for this instance.")
        time.sleep(SCREEN_APPEAR_POLL_SECONDS)
    return screen


@route("GET", "/api/signin/screen")
def signin_screen(h: Handler) -> None:
    screen = _screen_of(h)
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("Cache-Control", "no-cache")
    h.end_headers()
    seen = -1
    try:
        while not screen.closed:
            if not screen.wait(seen, PING_SECONDS):
                h.wfile.write(b"event: ping\ndata: \n\n")
                h.wfile.flush()
                continue
            seen = screen.seq
            if screen.frame is not None:
                h.wfile.write(f"data: {json.dumps(screen.frame)}\n\n".encode())
                h.wfile.flush()
        h.wfile.write(b"event: end\ndata: \n\n")
        h.wfile.flush()
    except OSError:
        pass


@route("POST", "/api/signin/input")
def signin_input(h: Handler) -> dict[str, bool]:
    events = h.json().get("events")
    if not isinstance(events, list):
        raise HttpError(400, "Give a list of events.")
    _screen_of(h).push(events)
    return {"ok": True}


@route("POST", "/api/signin/cancel")
def signin_cancel(h: Handler) -> dict[str, bool]:
    screen = find_screen(screen_key(_required(h.query, "url"), h.query.get("tenant", "")))
    if screen is not None:
        screen.cancel.set()
    return {"ok": True}


@route("GET", "/api/runs/([a-z0-9]+)/events")
def run_events(h: Handler, run_id: str) -> None:
    run = _run(run_id)
    last = int(_required(h.query, "after"))
    channel, unsubscribe, backlog = run.resume(last)
    try:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.end_headers()
        for stored in backlog:
            _write_event(h, stored)
            last = stored["seq"]
        while True:
            try:
                stored = channel.get(timeout=PING_SECONDS)
            except queue.Empty:
                h.wfile.write(b"event: ping\ndata: \n\n")
                h.wfile.flush()
                continue
            if stored.get("live") or stored["seq"] > last:
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
    _run(run_id).answer(_required(data, "questionId"), _required(data, "answer"))
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/login")
def run_login(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    run = _run(run_id)
    login_id = _required(data, "loginId")
    if not any(item["id"] == login_id for item in run.state["logins"]):
        raise HttpError(404, "No such login prompt.")

    threading.Thread(target=run.login, args=(login_id, bool(data.get("skip"))), daemon=True).start()
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/message")
def message(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    files = _objects(data, "files")
    _run(run_id).follow_up(str(data.get("text", "")), files)
    db.set_settled(run_id, False)
    status_feed.publish({"kind": "list"})
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/title")
def rename(h: Handler, run_id: str) -> dict[str, bool]:
    _run(run_id).rename(_required(h.json(), "title"))
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/retry")
def retry(h: Handler, run_id: str) -> dict[str, bool]:
    _run(run_id).retry(_required(h.json(), "itemId"))
    return {"ok": True}


@route("DELETE", "/api/runs/([a-z0-9]+)/queued/([^/]+)")
def remove_queued(_: Handler, run_id: str, message_id: str) -> dict[str, bool]:
    _run(run_id).remove_queued(message_id)
    return {"ok": True}


@route("POST", "/api/runs/([a-z0-9]+)/rate")
def rate(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    _run(run_id).rate(_required(data, "turnId"), data.get("rating"), data.get("note"))
    return {"ok": True}


@route("GET", "/api/runs/([a-z0-9]+)/files/([^/]+)")
def run_file(h: Handler, run_id: str, name: str) -> None:
    _run(run_id)
    path = within(attachments_dir(run_id), Path(name).name)
    if not path.is_file():
        raise HttpError(404, "File not found.")

    suffix = path.suffix.lower()
    if suffix in INLINE_FILES:
        content_type, disposition = CONTENT_TYPES[suffix], "inline"
    else:
        content_type, disposition = "application/octet-stream", "attachment"
    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(path.name)}"}
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
        response = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
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
