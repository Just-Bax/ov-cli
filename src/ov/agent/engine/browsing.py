from __future__ import annotations

import hashlib
import itertools
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ov.agent.api.screen import Key, Screen, close_screen, open_screen
from ov.browser.dialogs import NO_DIALOG
from ov.browser.pilot import BrowserError, Pilot, Point

BROWSER_WIDTH = 1280
BROWSER_HEIGHT = 800
MAX_WIDTH = 1440
MAX_HEIGHT = 900
MIN_SIDE = 320
SCREEN_SCOPE = "run"
LOOP_ROUNDS = 3
LOOP_LONGEST = 4
NOT_OPEN = "No browser is open. Open one with browser_open first."
CLOSED_ITSELF = "The browser closed by itself."
MAX_USER_ACTIONS = 20
DIALOG_CHARS = 80
USER_ACTED = "The user worked in the browser themselves: {actions}."
USER_SHOWN = " It now shows {title} | {url}. Take a snapshot before you act there."
USER_SWITCHED_TAB = "switched to tab {index}"
USER_CLOSED_TAB = "closed tab {index}"
USER_ANSWERED = '{verb} the {kind} "{message}"'

_sessions = itertools.count(1)
_steps = itertools.count(1)
_stage = {"width": BROWSER_WIDTH, "height": BROWSER_HEIGHT}


def browser_key(run_id: str) -> Key:
    return SCREEN_SCOPE, run_id


def _clamp(value: int, top: int) -> int:
    return max(MIN_SIDE, min(top, value))


def loop_span(period: int) -> int:
    return period * LOOP_ROUNDS + 1


def _cycles(recent: list[str], period: int) -> bool:
    span = loop_span(period)
    if len(recent) < span:
        return False
    tail = recent[-span:]
    return all(tail[i] == tail[i + period] for i in range(span - period))


@dataclass(frozen=True)
class _Open:
    alias: str
    pilot: Pilot
    screen: Screen


class BrowserSlot:
    def __init__(self, run_id: str, emit: Callable[[dict[str, Any]], None]) -> None:
        self._key = browser_key(run_id)
        self._emit = emit
        self._lock = threading.Lock()
        self._open: _Open | None = None
        self._recent: deque[str] = deque(maxlen=loop_span(LOOP_LONGEST))
        self._seen = ""
        self._user_actions: deque[str] = deque(maxlen=MAX_USER_ACTIONS)
        self._shown: dict[str, Any] | None = None

    def saw(self, page: str) -> None:
        with self._lock:
            self._seen = hashlib.sha256(page.encode()).hexdigest()

    def looping(self, action: str) -> int:
        with self._lock:
            self._recent.append(f"{self._seen} {action}")
            recent = list(self._recent)
        return next((period for period in range(1, LOOP_LONGEST + 1) if _cycles(recent, period)), 0)

    @property
    def live(self) -> bool:
        with self._lock:
            return self._open is not None and self._open.pilot.alive

    def start(self, alias: str, base_url: str, cookies: dict[str, str]) -> Pilot:
        with self._lock:
            current = self._open

        if current is not None and current.alias == alias and current.pilot.alive:
            return current.pilot

        self.close()
        screen = open_screen(self._key, _stage["width"], _stage["height"])
        try:
            pilot = Pilot(base_url, cookies, screen.port, (screen.width, screen.height), self)
        except BrowserError:
            close_screen(self._key, screen)
            raise

        screen.follow = lambda: pilot.active_target
        screen.watch = self.user_did
        with self._lock:
            self._open = _Open(alias, pilot, screen)
            self._user_actions.clear()
            self._shown = None

        opened = {
            "open": True,
            "instance": alias,
            "session": next(_sessions),
            "pointer": None,
            "error": None,
            "loading": None,
            "dialog": None,
        }
        self._emit({"type": "browser", "browser": opened})
        return pilot

    def pilot(self) -> Pilot:
        with self._lock:
            current = self._open
        if current is None or not current.pilot.alive:
            raise BrowserError(NOT_OPEN)
        return current.pilot

    def navigate(self, url: str) -> None:
        pilot = self.pilot()
        self._emit({"type": "browser", "browser": {"loading": url}})
        try:
            pilot.goto(url)
        finally:
            self._emit({"type": "browser", "browser": {"loading": None}})

    def pointer(self, point: Point, press: bool) -> None:
        pointer = {"x": point.x, "y": point.y, "step": next(_steps), "press": press}
        self._emit({"type": "browser", "browser": {"pointer": pointer}})

    def answer_dialog(self, accept: bool, text: str) -> None:
        self.pilot().answer(accept, text)

    def switch_tab(self, index: int) -> None:
        self.pilot().switch(index)

    def close_tab(self, index: int) -> None:
        self.pilot().close_tab(index)

    def user_did(self, action: str) -> None:
        with self._lock:
            if not self._user_actions or self._user_actions[-1] != action:
                self._user_actions.append(action)

    def user_answered(self, accept: bool, text: str) -> None:
        pilot = self.pilot()
        shown = pilot.dialog
        if shown is None:
            raise BrowserError(NO_DIALOG)

        pilot.answer(accept, text)
        verb = "accepted" if accept else "dismissed"
        self.user_did(USER_ANSWERED.format(verb=verb, kind=shown.kind, message=shown.message[:DIALOG_CHARS]))

    def user_switched_tab(self, index: int) -> None:
        self.switch_tab(index)
        self.user_did(USER_SWITCHED_TAB.format(index=index))

    def user_closed_tab(self, index: int) -> None:
        self.close_tab(index)
        self.user_did(USER_CLOSED_TAB.format(index=index))

    def take_user_actions(self) -> str | None:
        with self._lock:
            actions = list(self._user_actions)
            self._user_actions.clear()
            shown = self._shown
        if not actions:
            return None

        note = USER_ACTED.format(actions="; ".join(actions))
        if shown is None:
            return note
        return note + USER_SHOWN.format(title=shown["title"] or shown["url"], url=shown["url"])

    def resize(self, width: int, height: int) -> None:
        _stage.update(width=_clamp(width, MAX_WIDTH), height=_clamp(height, MAX_HEIGHT))
        self.pilot().resize(_stage["width"], _stage["height"])

    def close(self) -> None:
        current = self._take(None)
        if current is None:
            return
        current.pilot.close()
        close_screen(self._key, current.screen)
        self._emit({"type": "browser", "browser": {"open": False, "dialog": None, "tabs": []}})

    def changed(self, change: dict[str, Any]) -> None:
        active = next((tab for tab in change.get("tabs", []) if tab["active"]), None)
        if active is not None:
            with self._lock:
                self._shown = active
        self._emit({"type": "browser", "browser": change})

    def exited(self, pilot: Pilot) -> None:
        current = self._take(pilot)
        if current is None:
            return
        close_screen(self._key, current.screen)
        self._emit(
            {
                "type": "browser",
                "browser": {"open": False, "dialog": None, "tabs": [], "error": pilot.failure or CLOSED_ITSELF},
            }
        )

    def _take(self, pilot: Pilot | None) -> _Open | None:
        with self._lock:
            current = self._open
            if current is None or (pilot is not None and current.pilot is not pilot):
                return None
            self._open = None
            return current
