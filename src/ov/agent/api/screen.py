from __future__ import annotations

import contextlib
import queue
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ov.agent.engine.cancel import Cancel
from ov.onevizion.login import SCREEN_PORT_ENV, SCREEN_SIZE_ENV

CONNECT_WAIT_SECONDS = 600
CONNECT_RETRY_SECONDS = 0.5
LOOPBACK_HOST = "127.0.0.1"
LOOP_MS = 15
JPEG_QUALITY = 75
FRAME_INTERVAL_SECONDS = 1 / 15
MIN_SIDE = 320
MAX_WIDTH = 1600
MAX_HEIGHT = 1200
MAX_EVENTS = 200
MAX_TEXT_CHARS = 2000

MOUSE_EVENTS = {"mousePressed", "mouseReleased", "mouseMoved"}
KEY_EVENTS = {"keyDown", "keyUp", "rawKeyDown", "char"}
BUTTONS = {"none", "left", "middle", "right"}
COMMANDS = {"selectAll", "undo", "redo"}

Key = tuple[str, str]
Follow = Callable[[], str | None]


class ScreenError(Exception):
    pass


def screen_key(url: str, tenant: str) -> Key:
    return url.strip().rstrip("/").lower(), tenant.strip().lower()


def clamp_size(width: int, height: int) -> tuple[int, int]:
    return max(MIN_SIDE, min(MAX_WIDTH, width)), max(MIN_SIDE, min(MAX_HEIGHT, height))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((LOOPBACK_HOST, 0))
        return sock.getsockname()[1]


class Screen:
    def __init__(self, width: int, height: int) -> None:
        self.port = _free_port()
        self.width, self.height = clamp_size(width, height)
        self.frame: dict[str, Any] | None = None
        self.seq = 0
        self.closed = False
        self.failure: str | None = None
        self.cancel = Cancel()
        self.follow: Follow | None = None
        self._changed = threading.Condition()
        self._input: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="signin-screen", daemon=True)

    @property
    def env(self) -> dict[str, str]:
        return {SCREEN_PORT_ENV: str(self.port), SCREEN_SIZE_ENV: f"{self.width}x{self.height}"}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def push(self, events: list[dict[str, Any]]) -> None:
        if self.closed:
            raise ScreenError("The sign-in browser has closed.")
        for event in events[:MAX_EVENTS]:
            self._input.put(_checked(event))

    def wait(self, seen: int, timeout: float) -> bool:
        with self._changed:
            return self._changed.wait_for(lambda: self.seq != seen or self.closed, timeout)

    def _publish(self, frame: dict[str, Any] | None = None) -> None:
        with self._changed:
            if frame is not None:
                self.frame = frame
            self.seq += 1
            self._changed.notify_all()

    def _run(self) -> None:
        try:
            with sync_playwright() as p:
                browser = self._connect(p)
                if browser is None:
                    self.failure = "The sign-in browser did not start."
                else:
                    self._mirror(browser.contexts[0])
        except PlaywrightError as exc:
            self.failure = None if self._stop.is_set() or self.frame is not None else str(exc).splitlines()[0]
        finally:
            self.closed = True
            self._publish()

    def _connect(self, p: Any) -> Any:
        deadline = time.monotonic() + CONNECT_WAIT_SECONDS
        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                return p.chromium.connect_over_cdp(f"http://{LOOPBACK_HOST}:{self.port}")
            except PlaywrightError:
                time.sleep(CONNECT_RETRY_SECONDS)

        return None

    def _mirror(self, context: Any) -> None:
        context.on("dialog", _leave_to_owner)
        feed = _Feed(self._publish)
        targets: dict[Any, str] = {}
        cdp: Any = None
        while not self._stop.is_set():
            pages = [pg for pg in context.pages if not pg.is_closed()]
            if not pages:
                return

            shown = self._shown(context, pages, targets, feed.page)
            if shown is not feed.page:
                cdp = feed.watch(context, shown, cdp)

            with contextlib.suppress(PlaywrightError):
                feed.flush(cdp)
                while not self._input.empty():
                    _apply(cdp, self._input.get())
                feed.page.wait_for_timeout(LOOP_MS)

    def _shown(self, context: Any, pages: list[Any], targets: dict[Any, str], current: Any) -> Any:
        if self.follow is None:
            return pages[-1]

        wanted = self.follow()
        for page in pages:
            if page not in targets:
                targets[page] = _target_id(context, page)
            if targets[page] == wanted:
                return page

        return current if current in pages else pages[-1]


def _target_id(context: Any, page: Any) -> str:
    session = context.new_cdp_session(page)
    target = session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
    session.detach()
    return target


def _leave_to_owner(_: Any) -> None:
    return None


class _Feed:
    def __init__(self, publish: Any) -> None:
        self.page: Any = None
        self._publish = publish
        self._acks: list[int] = []
        self._latest: dict[str, Any] | None = None
        self._shown_at = 0.0

    def watch(self, context: Any, page: Any, old: Any) -> Any:
        if old is not None:
            with contextlib.suppress(PlaywrightError):
                old.detach()

        self.page = page
        self._acks.clear()
        cdp = context.new_cdp_session(page)
        cdp.on("Page.screencastFrame", self._on_frame)
        cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": JPEG_QUALITY, "maxWidth": MAX_WIDTH, "maxHeight": MAX_HEIGHT},
        )
        return cdp

    def _on_frame(self, event: dict[str, Any]) -> None:
        self._acks.append(event["sessionId"])
        meta = event["metadata"]
        self._latest = {
            "data": event["data"],
            "url": self.page.url,
            "width": meta["deviceWidth"],
            "height": meta["deviceHeight"],
        }

    def flush(self, cdp: Any) -> None:
        if self._latest is None or time.monotonic() - self._shown_at < FRAME_INTERVAL_SECONDS:
            return

        self._publish(self._latest)
        self._latest = None
        self._shown_at = time.monotonic()
        while self._acks:
            cdp.send("Page.screencastFrameAck", {"sessionId": self._acks.pop(0)})


def _number(event: dict[str, Any], key: str, kind: type = float) -> Any:
    value = event.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScreenError(f"Input {key} must be a number.")
    return kind(value)


def _checked(event: dict[str, Any]) -> dict[str, Any]:
    kind = event.get("type")
    if kind == "mouse" and event.get("event") in MOUSE_EVENTS and event.get("button", "none") in BUTTONS:
        return {
            "type": kind,
            "event": event["event"],
            "x": _number(event, "x"),
            "y": _number(event, "y"),
            "button": event.get("button", "none"),
            "buttons": _number(event, "buttons", int),
            "clickCount": _number(event, "clickCount", int),
            "modifiers": _number(event, "modifiers", int),
        }

    if kind == "wheel":
        return {
            "type": kind,
            "x": _number(event, "x"),
            "y": _number(event, "y"),
            "dx": _number(event, "dx"),
            "dy": _number(event, "dy"),
        }

    if kind == "back":
        return {"type": kind}
    if kind == "key" and event.get("event") in KEY_EVENTS:
        commands = event.get("commands") or []
        if not isinstance(commands, list):
            raise ScreenError("Input commands must be a list.")

        return {
            "type": kind,
            "event": event["event"],
            "key": str(event.get("key", "")),
            "code": str(event.get("code", "")),
            "keyCode": _number(event, "keyCode", int),
            "modifiers": _number(event, "modifiers", int),
            "text": str(event["text"]) if event.get("text") else None,
            "commands": [c for c in commands if c in COMMANDS],
        }

    if kind == "text" and isinstance(event.get("text"), str):
        return {"type": kind, "text": event["text"][:MAX_TEXT_CHARS]}
    raise ScreenError(f"Unknown input: {kind}")


def _apply(cdp: Any, event: dict[str, Any]) -> None:
    kind = event["type"]
    if kind == "mouse":
        cdp.send(
            "Input.dispatchMouseEvent",
            {**{k: v for k, v in event.items() if k not in ("type", "event")}, "type": event["event"]},
        )
    elif kind == "wheel":
        cdp.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": event["x"], "y": event["y"], "deltaX": event["dx"], "deltaY": event["dy"]},
        )
    elif kind == "key":
        params: dict[str, Any] = {
            "type": event["event"],
            "key": event["key"],
            "code": event["code"],
            "windowsVirtualKeyCode": event["keyCode"],
            "modifiers": event["modifiers"],
        }
        if event["text"]:
            params["text"] = params["unmodifiedText"] = event["text"]
        if event["commands"]:
            params["commands"] = event["commands"]
        cdp.send("Input.dispatchKeyEvent", params)
    elif kind == "text":
        cdp.send("Input.insertText", {"text": event["text"]})
    elif kind == "back":
        cdp.send("Runtime.evaluate", {"expression": "history.back()"})


_screens: dict[Key, Screen] = {}
_lock = threading.Lock()


def open_screen(key: Key, width: int, height: int) -> Screen:
    screen = Screen(width, height)
    with _lock:
        _screens[key] = screen
    screen.start()
    return screen


def close_screen(key: Key, screen: Screen) -> None:
    screen.stop()
    with _lock:
        if _screens.get(key) is screen:
            del _screens[key]


def find_screen(key: Key) -> Screen | None:
    with _lock:
        return _screens.get(key)
