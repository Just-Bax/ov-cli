from __future__ import annotations

import pytest


def test_bad_sign_in_input_is_refused():
    from ov.agent.api.screen import ScreenError, _checked

    assert _checked({"type": "mouse", "event": "mousePressed", "x": 3, "y": 4, "button": "left"})["x"] == 3.0

    for bad in (
        {"type": "mouse", "event": "mousePressed", "x": "a", "y": 1},
        {"type": "wheel", "x": 1, "y": 1, "dx": None},
        {"type": "key", "event": "keyDown", "keyCode": "13"},
        {"type": "eval"},
    ):
        with pytest.raises(ScreenError):
            _checked(bad)


class _Page:
    def __init__(self) -> None:
        self.url = "https://acme.onevizion.test/Login.do"

    def is_closed(self) -> bool:
        return False

    def wait_for_timeout(self, ms: int) -> None:
        pass


class _Cdp:
    def __init__(self, fails: bool) -> None:
        self.fails = fails

    def on(self, event, handler) -> None:
        pass

    def send(self, method, params=None):
        if self.fails and method == "Page.startScreencast":
            from playwright.sync_api import Error

            raise Error("Protocol error (Page.startScreencast): Not attached to an active page")
        return {}

    def detach(self) -> None:
        pass


class _Context:
    def __init__(self, failures: int, screen) -> None:
        self.pages = [_Page()]
        self.failures = failures
        self.sessions = 0
        self.screen = screen

    def on(self, event, handler) -> None:
        pass

    def new_cdp_session(self, page):
        self.sessions += 1
        if self.sessions > self.failures:
            self.screen.stop()
        return _Cdp(self.sessions <= self.failures)


def test_a_page_that_detaches_while_attaching_is_attached_again(monkeypatch):
    from ov.agent.api import screen as module

    monkeypatch.setattr(module, "ATTACH_RETRY_SECONDS", 0)
    shown = module.Screen(800, 600)
    context = _Context(2, shown)

    shown._mirror(context)
    assert context.sessions == 3


def test_a_page_that_never_attaches_still_fails(monkeypatch):
    from playwright.sync_api import Error

    from ov.agent.api import screen as module

    monkeypatch.setattr(module, "ATTACH_RETRY_SECONDS", 0)
    shown = module.Screen(800, 600)

    with pytest.raises(Error, match="Not attached"):
        shown._mirror(_Context(module.ATTACH_ATTEMPTS, shown))
