from __future__ import annotations

from ov.agent.api.handler import Handler, HttpError, route
from ov.agent.api.routes.threads import require_run, require_thread
from ov.agent.api.screen import find_screen
from ov.agent.api.streams import push_input, stream_screen
from ov.agent.engine.browsing import browser_key


@route("GET", "/api/threads/([a-z0-9]+)/browser/screen")
def browser_screen(h: Handler, run_id: str) -> None:
    require_thread(run_id)
    screen = find_screen(browser_key(run_id))
    if screen is None:
        raise HttpError(404, "No browser is open in this thread.")
    stream_screen(h, screen)


@route("POST", "/api/threads/([a-z0-9]+)/browser/input")
def browser_input(h: Handler, run_id: str) -> dict[str, bool]:
    require_thread(run_id)
    return push_input(h, find_screen(browser_key(run_id)))


@route("POST", "/api/threads/([a-z0-9]+)/browser/open")
def browser_open(h: Handler, run_id: str) -> dict[str, bool]:
    require_run(run_id).open_browser(str(h.json().get("instance") or ""))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/browser/size")
def browser_size(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    require_run(run_id).browser.resize(int(data["width"]), int(data["height"]))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/browser/dialog")
def browser_dialog(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    require_run(run_id).browser.user_answered(data.get("accept") is True, str(data.get("text") or ""))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/browser/tab")
def browser_tab(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    browser = require_run(run_id).browser
    if data.get("close") is True:
        browser.user_closed_tab(int(data["index"]))
    else:
        browser.user_switched_tab(int(data["index"]))

    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/browser/close")
def browser_close(_: Handler, run_id: str) -> dict[str, bool]:
    require_run(run_id).close_browser()
    return {"ok": True}
