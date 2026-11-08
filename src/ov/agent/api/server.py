from __future__ import annotations

import math
import os
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer

import httpx

from ov.agent import providers
from ov.agent.api import session
from ov.agent.api.handler import APP_ID, LOOPBACK_HOST, Handler
from ov.agent.api.routes import browser, instances, integrations, settings, threads
from ov.agent.api.terminal import AgentTerminal
from ov.agent.engine.run_manager import runs
from ov.agent.storage import db
from ov.agent.tools import plsql as plsql_tool
from ov.core.errors import EXIT_INTERRUPTED, OvError

DEFAULT_PORT = 5180
HEALTH_CHECK_TIMEOUT_SECONDS = 2
SHUTDOWN_DEADLINE_SECONDS = 15
WAIT_SLICE_SECONDS = 0.25
ROUTE_MODULES = (settings, instances, integrations, threads, browser)


class AgentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address: tuple[str, int], handler: type[Handler]) -> None:
        super().__init__(address, handler)
        self.session_token = session.token()


def already_running(port: int) -> bool:
    try:
        response = httpx.get(f"{_local_url(port)}/api/health", timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        return response.json().get("app") == APP_ID
    except (httpx.HTTPError, ValueError):
        return False


def _local_url(port: int) -> str:
    return f"http://{LOOPBACK_HOST}:{port}"


def serve(
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    full_access: bool = False,
    plsql: bool = False,
    color: bool = True,
) -> int:
    url = session.link(_local_url(port), session.token())
    terminal = AgentTerminal(color)
    try:
        server = AgentServer((LOOPBACK_HOST, port), Handler)
    except OSError:
        if not already_running(port):
            raise OvError(f"Port {port} is in use by another program. Pass --port.") from None
        flags = " ".join(flag for flag, on in (("--full-access", full_access), ("--allow-plsql", plsql)) if on)
        if flags:
            raise OvError(
                f"OV Agent is already running at {_local_url(port)}. Stop it, then start it with {flags}."
            ) from None
        terminal.already_running(url)
        if open_browser:
            webbrowser.open(url)
        return 0

    try:
        db.migrate()
    except OvError:
        server.server_close()
        raise

    runs.full_access = full_access
    if plsql:
        plsql_tool.enable()
    runs.resume_interrupted()
    terminal.started(url, full_access, plsql)

    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

    return _serve_until_stopped(server, terminal)


def _wait(thread: threading.Thread, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while thread.is_alive() and time.monotonic() < deadline:
        thread.join(WAIT_SLICE_SECONDS)


def _run(server: AgentServer, failures: list[BaseException]) -> None:
    try:
        server.serve_forever()
    except BaseException as exc:
        failures.append(exc)


def _close(server: AgentServer, failures: list[BaseException]) -> None:
    try:
        server.shutdown()
        server.server_close()
        runs.close()
        providers.close_all()
        db.close()
    except BaseException as exc:
        failures.append(exc)


def _serve_until_stopped(server: AgentServer, terminal: AgentTerminal) -> int:
    failures: list[BaseException] = []
    serving = threading.Thread(target=_run, args=(server, failures), name="agent-http", daemon=True)
    serving.start()
    try:
        _wait(serving, math.inf)
    except KeyboardInterrupt:
        terminal.stopping()

    closing = threading.Thread(target=_close, args=(server, failures), name="agent-close", daemon=True)
    closing.start()
    try:
        _wait(closing, SHUTDOWN_DEADLINE_SECONDS)
    except KeyboardInterrupt:
        terminal.forced()
        os._exit(EXIT_INTERRUPTED)

    if closing.is_alive():
        terminal.gave_up(SHUTDOWN_DEADLINE_SECONDS)
        os._exit(EXIT_INTERRUPTED)

    if failures:
        raise failures[0]

    terminal.stopped()
    return 0
