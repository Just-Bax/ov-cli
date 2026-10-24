from __future__ import annotations

import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer

import httpx

from ov.agent import providers
from ov.agent.api.handler import APP_ID, LOOPBACK_HOST, Handler
from ov.agent.api.routes import browser, instances, integrations, settings, threads
from ov.agent.engine.run_manager import runs
from ov.agent.storage import db
from ov.core.errors import OvError

DEFAULT_PORT = 5180
HEALTH_CHECK_TIMEOUT_SECONDS = 2
ROUTE_MODULES = (settings, instances, integrations, threads, browser)


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"


def already_running(port: int) -> bool:
    try:
        response = httpx.get(f"{_local_url(port)}/api/health", timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        return response.json().get("app") == APP_ID
    except (httpx.HTTPError, ValueError):
        return False


def _local_url(port: int) -> str:
    return f"http://{LOOPBACK_HOST}:{port}"


def serve(port: int = DEFAULT_PORT, open_browser: bool = True, full_access: bool = False) -> int:
    url = _local_url(port)
    try:
        server = AgentServer((LOOPBACK_HOST, port), Handler)
    except OSError:
        if not already_running(port):
            raise OvError(f"Port {port} is in use by another program. Pass --port.") from None
        if full_access:
            raise OvError(f"OV Agent is already running at {url}. Stop it, then start it with --full-access.") from None
        print(f"OV Agent is already running at {url}")
        if open_browser:
            webbrowser.open(url)
        return 0

    try:
        db.migrate()
    except OvError:
        server.server_close()
        raise

    runs.full_access = full_access
    runs.resume_interrupted()
    print(f"OV Agent running at {url}  (Ctrl+C to stop)", flush=True)
    if full_access:
        print("Full access is available: threads set to it change anything without asking.", flush=True)

    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    _serve_until_stopped(server)
    return 0


def _serve_until_stopped(server: AgentServer) -> None:
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runs.close()
        providers.close_all()
        db.close()
