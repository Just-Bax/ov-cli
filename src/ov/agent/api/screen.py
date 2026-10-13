from __future__ import annotations

import contextlib
import queue
import socket
import threading
import time
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
        page: Any = None
        cdp: Any = None
        acks: list[int] = []

        def on_frame(event: dict[str, Any]) -> None:
            acks.append(event["sessionId"])
            meta = event["metadata"]
            self._publish(
                {
                    "data": event["data"],
                    "url": page.url,
                    "width": meta["deviceWidth"],
                    "height": meta["deviceHeight"],
                }
            )

        while not self._stop.is_set():
            pages = [pg for pg in context.pages if not pg.is_closed()]
            if not pages:
                return
            if pages[-1] is not page:
                if cdp is not None:
                    with contextlib.suppress(PlaywrightError):
                        cdp.detach()
                page = pages[-1]
                cdp = context.new_cdp_session(page)
                cdp.on("Page.screencastFrame", on_frame)
                cdp.send("Page.startScreencast", {"format": "jpeg", "quality": JPEG_QUALITY})
                acks.clear()

            with contextlib.suppress(PlaywrightError):
                while acks:
                    cdp.send("Page.screencastFrameAck", {"sessionId": acks.pop(0)})
                while not self._input.empty():
                    _apply(cdp, self._input.get())
                page.wait_for_timeout(LOOP_MS)


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
