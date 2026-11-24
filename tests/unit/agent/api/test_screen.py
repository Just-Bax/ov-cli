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


SNAPSHOT_REPLIES = {
    "Page.captureScreenshot": {"data": "c25hcA=="},
    "Page.getLayoutMetrics": {"cssVisualViewport": {"clientWidth": 800, "clientHeight": 600}},
}


class _Cdp:
    def __init__(self, fails: bool) -> None:
        self.fails = fails
        self.sent: list[str] = []

    def on(self, event, handler) -> None:
        pass

    def send(self, method, params=None):
        self.sent.append(method)
        if self.fails and method == "Page.startScreencast":
            from playwright.sync_api import Error

            raise Error("Protocol error (Page.startScreencast): Not attached to an active page")
        return SNAPSHOT_REPLIES.get(method, {})

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
        self.cdp = _Cdp(self.sessions <= self.failures)
        return self.cdp


def test_a_page_that_detaches_while_attaching_is_attached_again(monkeypatch):
    from ov.agent.api import screen as module

    monkeypatch.setattr(module, "ATTACH_RETRY_SECONDS", 0)
    shown = module.Screen(800, 600, False)
    context = _Context(2, shown)

    with shown.viewing():
        shown._mirror(context)
    assert context.sessions == 3


def test_nothing_is_cast_while_nobody_watches():
    from ov.agent.api import screen as module

    shown = module.Screen(800, 600, False)
    context = _Context(0, shown)

    shown._mirror(context)
    assert "Page.startScreencast" not in context.cdp.sent
    assert shown.frame is None


def test_a_viewer_gets_the_current_picture_at_once():
    from ov.agent.api import screen as module

    shown = module.Screen(800, 600, False)
    context = _Context(0, shown)

    with shown.viewing():
        shown._mirror(context)
    assert context.cdp.sent[:2] == ["Page.startScreencast", "Page.captureScreenshot"]
    assert shown.frame == {"data": "c25hcA==", "url": _Page().url, "width": 800, "height": 600}


def test_casting_stops_when_the_last_viewer_leaves():
    from ov.agent.api.screen import _Feed

    feed = _Feed(lambda frame=None: None)
    feed.page = _Page()
    cdp = _Cdp(False)

    feed.cast(cdp, True)
    feed.cast(cdp, True)
    feed.cast(cdp, False)
    assert cdp.sent.count("Page.startScreencast") == 1
    assert cdp.sent[-1] == "Page.stopScreencast"


def test_a_page_that_never_attaches_still_fails(monkeypatch):
    from playwright.sync_api import Error

    from ov.agent.api import screen as module

    monkeypatch.setattr(module, "ATTACH_RETRY_SECONDS", 0)
    shown = module.Screen(800, 600, False)

    with pytest.raises(Error, match="Not attached"), shown.viewing():
        shown._mirror(_Context(module.ATTACH_ATTEMPTS, shown))


class _DescribingCdp:
    def __init__(self, found) -> None:
        self.found = found
        self.sent: list[str] = []

    def send(self, method, params=None):
        self.sent.append(method)
        if method == "DOM.getNodeForLocation":
            return {"backendNodeId": 7}
        if method == "DOM.resolveNode":
            return {"object": {"objectId": "o1"}}
        if method == "Runtime.callFunctionOn":
            return {"result": {"value": self.found}}
        return {}


SAVE = {"role": "button", "name": "Save", "value": "", "area": "Edit", "disabled": False, "x": 3, "y": 4}


@pytest.mark.parametrize(
    ("event", "found", "action"),
    [
        ({"type": "mouse", "event": "mousePressed", "x": 3.2, "y": 4.4}, SAVE, 'clicked button "Save" in "Edit"'),
        ({"type": "mouse", "event": "mousePressed", "x": 3, "y": 4}, None, "clicked empty space at (3, 4)"),
        ({"type": "mouse", "event": "mouseMoved", "x": 3, "y": 4}, SAVE, None),
        ({"type": "key", "event": "keyDown", "key": "a"}, None, "typed on the keyboard"),
        ({"type": "key", "event": "rawKeyDown", "key": "Enter"}, None, "pressed Enter"),
        ({"type": "key", "event": "keyUp", "key": "a"}, None, None),
        ({"type": "wheel"}, None, "scrolled"),
        ({"type": "text", "text": "x"}, None, "pasted text"),
        ({"type": "back"}, None, "went back a page"),
        ({"type": "reload"}, None, "reloaded the page"),
    ],
)
def test_what_the_user_does_on_the_screen_is_put_in_words(event, found, action):
    from ov.agent.api.screen import _user_action

    cdp = _DescribingCdp(found)
    assert _user_action(cdp, event) == action
    if event.get("event") == "mousePressed":
        assert cdp.sent[-1] == "Runtime.releaseObjectGroup"


def test_reload_is_an_input_the_screen_takes():
    from ov.agent.api.screen import _apply, _checked

    cdp = _DescribingCdp(None)
    _apply(cdp, _checked({"type": "reload"}))
    assert cdp.sent == ["Page.reload"]
