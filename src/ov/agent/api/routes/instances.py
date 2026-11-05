from __future__ import annotations

import re
import time
from typing import Any

import httpx

from ov.agent.api.handler import Handler, HttpError, required, route
from ov.agent.api.screen import Screen, find_screen, screen_key
from ov.agent.api.streams import push_input, stream_screen
from ov.agent.instances import access, explorer, graph
from ov.agent.instances.ovproc import find_instance, instances, login, remember, run_ov, url_for
from ov.onevizion.auth import LOGIN_PATH

LOGOUT_TIMEOUT_SECONDS = 60
LOGOUT_MESSAGE_CHARS = 300
LOGIN_MESSAGE_CHARS = 400
INSTANCE_CHECK_TIMEOUT_SECONDS = 20
_PLATFORM_VERSION = re.compile(r'Version\s*=\s*"([^"]+)"')
SCREEN_APPEAR_SECONDS = 10
SCREEN_APPEAR_POLL_SECONDS = 0.2


def instance_alias(h: Handler, ref: str | None = None) -> str:
    ref = (h.query.get("instance", "") if ref is None else ref).strip()
    found = next((i for i in instances() if i["alias"] == ref), None)
    if found is None:
        raise HttpError(404, f"Unknown instance: {ref}")
    return found["alias"]


def screen_size(data: dict[str, Any]) -> tuple[int, int] | None:
    screen = data.get("screen")
    return (int(screen["width"]), int(screen["height"])) if screen else None


def _with_access() -> list[dict[str, Any]]:
    return [{**row, "access": access.status(row["alias"])} for row in instances()]


@route("GET", "/api/instances")
def list_instances(_: Handler) -> list[dict[str, Any]]:
    return _with_access()


@route("POST", "/api/instances/access")
def check_access(h: Handler) -> list[dict[str, Any]]:
    alias = instance_alias(h, required(h.json(), "alias"))
    try:
        access.check(alias)
    except access.AccessError as exc:
        raise HttpError(400, str(exc)) from None
    return _with_access()


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

    result = login(url, tenant, token, screen_size(data), bool(data.get("remember")))
    return {"ok": result.code == 0, "message": result.message[-LOGIN_MESSAGE_CHARS:]}


@route("POST", "/api/instances/remember")
def remember_instance(h: Handler) -> list[dict[str, Any]]:
    alias = instance_alias(h, required(h.json(), "alias"))
    result = remember(alias)
    if result.code != 0:
        raise HttpError(400, result.message[-LOGIN_MESSAGE_CHARS:] or "Could not create the token.")
    return _with_access()


@route("GET", "/api/instances/check")
def check_instance(h: Handler) -> dict[str, Any]:
    ref = required(h.query, "instance")
    found = find_instance(ref)
    url = found["url"] if found else url_for(ref)
    started = time.monotonic()
    try:
        page = httpx.get(f"{url}{LOGIN_PATH}", timeout=INSTANCE_CHECK_TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise HttpError(502, f"{url} did not answer: {exc}") from None

    took = int((time.monotonic() - started) * 1000)
    if page.status_code >= 400:
        raise HttpError(502, f"{url} answered {page.status_code}.")

    found = _PLATFORM_VERSION.search(page.text)
    return {"url": url, "ms": took, "version": found.group(1) if found else None}


@route("POST", "/api/instances/logout")
def logout_instance(h: Handler) -> list[dict[str, Any]]:
    alias = instance_alias(h, required(h.json(), "alias"))
    result = run_ov(["logout", alias, "--json"], timeout=LOGOUT_TIMEOUT_SECONDS, read_only=False)
    if result.code != 0:
        raise HttpError(400, result.message[-LOGOUT_MESSAGE_CHARS:] or "Could not remove the instance.")
    return _with_access()


@route("GET", "/api/graph/status")
def graph_status(h: Handler) -> dict[str, Any]:
    return graph.status(instance_alias(h))


@route("POST", "/api/graph/build")
def graph_build(h: Handler) -> dict[str, Any]:
    alias = instance_alias(h, required(h.json(), "instance"))
    explorer.forget(alias)
    return graph.start_build(alias)


@route("GET", "/api/graph")
def graph_get(h: Handler) -> str:
    path = graph.graph_file(instance_alias(h))
    if not path.is_file():
        raise HttpError(404, "No map built for this instance yet.")
    return path.read_text(encoding="utf-8")


@route("GET", "/api/explorer/source")
def explorer_source(h: Handler) -> dict[str, Any]:
    return explorer.source(instance_alias(h), h.query.get("id", ""))


@route("GET", "/api/explorer/activity")
def explorer_activity(h: Handler) -> list[dict[str, Any]]:
    return explorer.activity(instance_alias(h), h.query.get("id", ""))


def _screen_of(h: Handler) -> Screen:
    key = screen_key(required(h.query, "url"), h.query.get("tenant", ""))
    deadline = time.monotonic() + SCREEN_APPEAR_SECONDS
    while (screen := find_screen(key)) is None:
        if time.monotonic() > deadline:
            raise HttpError(404, "No sign-in browser is open for this instance.")
        time.sleep(SCREEN_APPEAR_POLL_SECONDS)

    return screen


@route("GET", "/api/signin/screen")
def signin_screen(h: Handler) -> None:
    stream_screen(h, _screen_of(h))


@route("POST", "/api/signin/input")
def signin_input(h: Handler) -> dict[str, bool]:
    return push_input(h, find_screen(screen_key(required(h.query, "url"), h.query.get("tenant", ""))))


@route("POST", "/api/signin/cancel")
def signin_cancel(h: Handler) -> dict[str, bool]:
    screen = find_screen(screen_key(required(h.query, "url"), h.query.get("tenant", "")))
    if screen is not None:
        screen.cancel.set()
    return {"ok": True}
