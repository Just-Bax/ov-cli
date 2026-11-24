from __future__ import annotations

import contextlib
import queue
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from ov.agent.engine.cancel import Cancel
from ov.browser.model import Element, first_line
from ov.browser.reader import NAME_CHARS, VALUE_CHARS
from ov.browser.scripts import NODE_SCRIPT
from ov.onevizion.login import SCREEN_BOOST_ENV, SCREEN_PORT_ENV, SCREEN_SIZE_ENV

CONNECT_WAIT_SECONDS = 600
CONNECT_RETRY_SECONDS = 0.5
LOOPBACK_HOST = "127.0.0.1"
LOOP_MS = 15
ACTIVE_SECONDS = 1.0
UNWATCHED_PAUSE_SECONDS = 0.25
JPEG_QUALITY = 75
FRAME_INTERVAL_SECONDS = 1 / 15
MIN_SIDE = 320
MAX_WIDTH = 1600
MAX_HEIGHT = 1200
SCREENCAST = {"format": "jpeg", "quality": JPEG_QUALITY, "maxWidth": MAX_WIDTH, "maxHeight": MAX_HEIGHT}
SNAPSHOT = {"format": "jpeg", "quality": JPEG_QUALITY}
MAX_EVENTS = 200
MAX_TEXT_CHARS = 2000
ATTACH_ATTEMPTS = 20
ATTACH_RETRY_SECONDS = 0.25

MOUSE_EVENTS = {"mousePressed", "mouseReleased", "mouseMoved"}
KEY_EVENTS = {"keyDown", "keyUp", "rawKeyDown", "char"}
BUTTONS = {"none", "left", "middle", "right"}
COMMANDS = {"selectAll", "undo", "redo"}
NAVIGATION: dict[str, tuple[str, dict[str, Any]]] = {
    "back": ("Runtime.evaluate", {"expression": "history.back()"}),
    "reload": ("Page.reload", {}),
}
NAMED_KEYS = {"Enter", "Escape", "Tab"}
USER_GROUP = "ov-user-action"

CLICKED = "clicked {element}"
CLICKED_EMPTY = "clicked empty space at ({x}, {y})"
CLICKED_UNREAD = "clicked at ({x}, {y}), what is there could not be read: {reason}"
PRESSED_KEY = "pressed {key}"
TYPED = "typed on the keyboard"
PASTED = "pasted text"
SCROLLED = "scrolled"
NAVIGATION_ACTIONS = {"back": "went back a page", "reload": "reloaded the page"}

Key = tuple[str, str]
Follow = Callable[[], str | None]
Watch = Callable[[str], None]


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
    def __init__(self, width: int, height: int, boost: bool) -> None:
        self.port = _free_port()
        self.width, self.height = clamp_size(width, height)
        self.boost = boost
        self.frame: dict[str, Any] | None = None
        self.seq = 0
        self.closed = False
        self.failure: str | None = None
        self.cancel = Cancel()
        self.follow: Follow | None = None
        self.watch: Watch | None = None
        self._changed = threading.Condition()
        self._input: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._woken = threading.Event()
        self._viewers = 0
        self._acted_at = 0.0
        self._thread = threading.Thread(target=self._run, name="signin-screen", daemon=True)

    @property
    def env(self) -> dict[str, str]:
        return {
            SCREEN_PORT_ENV: str(self.port),
            SCREEN_SIZE_ENV: f"{self.width}x{self.height}",
            SCREEN_BOOST_ENV: "1" if self.boost else "0",
        }

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._woken.set()

    def push(self, events: list[dict[str, Any]]) -> None:
        if self.closed:
            raise ScreenError("The sign-in browser has closed.")
        for event in events[:MAX_EVENTS]:
            self._input.put(_checked(event))
        self._woken.set()

    @contextlib.contextmanager
    def viewing(self) -> Iterator[None]:
        with self._changed:
            self._viewers += 1
        self._woken.set()
        try:
            yield
        finally:
            with self._changed:
                self._viewers -= 1

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
        failed = 0
        while not self._stop.is_set():
            pages = [pg for pg in context.pages if not pg.is_closed()]
            if not pages:
                return

            try:
                cdp = self._follow(context, pages, targets, feed, cdp)
                feed.cast(cdp, self._viewers > 0)
            except PlaywrightError as exc:
                failed = _attach_failed(exc, failed, feed, targets)
                cdp = None
                continue

            failed = 0
            with contextlib.suppress(PlaywrightError):
                feed.flush(cdp)
                self._apply_input(cdp)
                self._rest(feed)

    def _apply_input(self, cdp: Any) -> None:
        while not self._input.empty():
            event = self._input.get()
            self._report(cdp, event)
            _apply(cdp, event)
            self._acted_at = time.monotonic()

    def _rest(self, feed: _Feed) -> None:
        if time.monotonic() - max(self._acted_at, feed.framed_at) < ACTIVE_SECONDS:
            feed.page.wait_for_timeout(LOOP_MS)
            return

        self._woken.wait(FRAME_INTERVAL_SECONDS if self._viewers else UNWATCHED_PAUSE_SECONDS)
        self._woken.clear()
        feed.page.wait_for_timeout(0)

    def _report(self, cdp: Any, event: dict[str, Any]) -> None:
        if self.watch is None:
            return

        action = _user_action(cdp, event)
        if action is not None:
            self.watch(action)

    def _follow(self, context: Any, pages: list[Any], targets: dict[Any, str], feed: _Feed, cdp: Any) -> Any:
        shown = self._shown(context, pages, targets, feed.page)
        if shown is feed.page:
            return cdp
        return feed.watch(context, shown, cdp)

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


def _user_action(cdp: Any, event: dict[str, Any]) -> str | None:
    kind = event["type"]
    if kind == "mouse":
        return _clicked(cdp, event["x"], event["y"]) if event["event"] == "mousePressed" else None
    if kind == "key":
        if event["event"] == "keyUp":
            return None
        return PRESSED_KEY.format(key=event["key"]) if event["key"] in NAMED_KEYS else TYPED

    if kind == "wheel":
        return SCROLLED
    if kind == "text":
        return PASTED
    return NAVIGATION_ACTIONS[kind]


def _clicked(cdp: Any, x: float, y: float) -> str:
    at = {"x": round(x), "y": round(y)}
    try:
        found = _element_at(cdp, at)
    except PlaywrightError as exc:
        return CLICKED_UNREAD.format(**at, reason=first_line(exc))
    finally:
        cdp.send("Runtime.releaseObjectGroup", {"objectGroup": USER_GROUP})

    if found is None:
        return CLICKED_EMPTY.format(**at)
    return CLICKED.format(element=Element(**found).describe())


def _element_at(cdp: Any, at: dict[str, int]) -> dict[str, Any] | None:
    hit = cdp.send("DOM.getNodeForLocation", {**at, "ignorePointerEventsNone": True})
    node = cdp.send("DOM.resolveNode", {"backendNodeId": hit["backendNodeId"], "objectGroup": USER_GROUP})
    found = cdp.send(
        "Runtime.callFunctionOn",
        {
            "objectId": node["object"]["objectId"],
            "functionDeclaration": NODE_SCRIPT,
            "arguments": [{"value": {**at, "nameChars": NAME_CHARS, "valueChars": VALUE_CHARS}}],
            "returnByValue": True,
        },
    )
    return found["result"].get("value")


def _attach_failed(exc: PlaywrightError, failed: int, feed: _Feed, targets: dict[Any, str]) -> int:
    if failed + 1 == ATTACH_ATTEMPTS:
        raise exc

    feed.page = None
    targets.clear()
    time.sleep(ATTACH_RETRY_SECONDS)
    return failed + 1


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
        self.casting = False
        self.framed_at = 0.0
        self._publish = publish
        self._acks: list[int] = []
        self._latest: dict[str, Any] | None = None
        self._shown_at = 0.0

    def watch(self, context: Any, page: Any, old: Any) -> Any:
        if old is not None:
            with contextlib.suppress(PlaywrightError):
                old.detach()

        self.page = page
        self.casting = False
        self._acks.clear()
        cdp = context.new_cdp_session(page)
        cdp.on("Page.screencastFrame", self._on_frame)
        return cdp

    def cast(self, cdp: Any, wanted: bool) -> None:
        if wanted == self.casting:
            return

        if not wanted:
            cdp.send("Page.stopScreencast")
            self.casting = False
            self._acks.clear()
            self._latest = None
            return

        cdp.send("Page.startScreencast", SCREENCAST)
        self.casting = True
        self._snapshot(cdp)

    def _snapshot(self, cdp: Any) -> None:
        shot = cdp.send("Page.captureScreenshot", SNAPSHOT)
        view = cdp.send("Page.getLayoutMetrics")["cssVisualViewport"]
        self._latest = {
            "data": shot["data"],
            "url": self.page.url,
            "width": view["clientWidth"],
            "height": view["clientHeight"],
        }
        self._shown_at = 0.0

    def _on_frame(self, event: dict[str, Any]) -> None:
        self.framed_at = time.monotonic()
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

    if kind in NAVIGATION:
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
    elif kind in NAVIGATION:
        cdp.send(*NAVIGATION[kind])


_screens: dict[Key, Screen] = {}
_lock = threading.Lock()


def open_screen(key: Key, width: int, height: int, boost: bool) -> Screen:
    screen = Screen(width, height, boost)
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
