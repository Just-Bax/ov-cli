from __future__ import annotations

import pytest
from helpers.agent import FakeContext

from ov.agent.engine.guard import Effect, Verdict
from ov.agent.tools import browser, tool_named
from ov.agent.tools.base import ToolError
from ov.browser.pilot import Aim, BrowserError, Dialog, DialogOpen, Element, Point, Tab, Target, View

SAVE = Element("button", "Save", "", "Edit Work Order", False, 130, 210, ref=2)
SEARCH = Element("textbox", "Search", "", "", False, 110, 20, ref=1)
CONFIRM = Dialog("confirm", "Delete record 42?", "")


class FakePilot:
    def __init__(self) -> None:
        self.done: list[str] = []
        self.url = "https://acme.onevizion.com/Dashboard.do"
        self.dialog: Dialog | None = None
        self.tabs = [Tab(1, "Work Order", self.url, True)]

    def where(self):
        return "Work Order", self.url

    def aim(self, target):
        if target.ref == 2:
            return Aim(SAVE.point, 'button "Save" at (130, 210)')
        if target.point is not None:
            return Aim(target.point, f"clickable at ({target.point.x}, {target.point.y})")
        return Aim(SEARCH.point, 'textbox "Search" at (110, 20)')

    def click(self, point, button, count, modifiers):
        self.done.append(f"click {point.x},{point.y} {button} x{count} {'+'.join(modifiers)}".strip())
        if self.dialog is not None:
            raise DialogOpen(self.dialog)

    def move(self, point):
        self.done.append(f"move {point.x},{point.y}")

    def press_mouse(self, point, button, down):
        self.done.append(f"{'down' if down else 'up'} {point.x},{point.y}")

    def drag(self, start, end):
        self.done.append(f"drag {start.x},{start.y} {end.x},{end.y}")

    def scroll(self, point, dx, dy):
        self.done.append(f"scroll {point.x},{point.y} {dx},{dy}")

    def type(self, text, clear):
        self.done.append(f"type {text}{' (clear)' if clear else ''}")

    def press(self, key):
        self.done.append(f"press {key}")

    def snapshot(self):
        return View(self.url, "Work Order", 1280, 800, [SEARCH, SAVE], [], self.tabs, "Work order WO-1")

    def screenshot(self):
        return b"jpeg"

    def take_blocked(self):
        return []


class FakeSlot:
    live = True

    def __init__(self, pilot: FakePilot) -> None:
        self._pilot = pilot
        self.pointers: list[tuple[Point, bool]] = []

    def pilot(self):
        return self._pilot

    def pointer(self, point, press):
        self.pointers.append((point, press))

    def answer_dialog(self, accept, text):
        self._pilot.done.append(f"{'accept' if accept else 'dismiss'} {text}".strip())
        self._pilot.dialog = None

    def switch_tab(self, index):
        self._pilot.done.append(f"switch {index}")


class BrowserContext(FakeContext):
    def __init__(self, tmp_path, write=False, approve="Approve", effect=Effect.READ):
        super().__init__(tmp_path, write=write, approve=approve)
        self.pilot = FakePilot()
        self.browser = FakeSlot(self.pilot)
        self.effect = effect
        self.actions: list[str] = []
        self.images: list[str] = []

    def judge_page_action(self, action):
        self.actions.append(action)
        return Verdict(self.effect, f"it is {self.effect.value}")

    def attach_image(self, name, url):
        self.images.append(name)


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(browser, "POINTER_LEAD_SECONDS", 0)


def test_a_click_moves_the_cursor_and_returns_a_screenshot(tmp_path):
    ctx = BrowserContext(tmp_path)
    out = tool_named("browser_click").handler({"x": 40, "y": 50, "say": "Opening the menu"}, ctx)
    assert ctx.pilot.done == ["click 40,50 left x1"] and ctx.asked == []
    assert ctx.browser.pointers == [(Point(40, 50), True)]
    assert len(ctx.images) == 1 and "Screenshot attached: 1280x800" in out
    assert "<intent>Opening the menu</intent>" in ctx.actions[0]


def test_without_vision_the_result_lists_elements_instead(tmp_path):
    ctx = BrowserContext(tmp_path)
    ctx.vision = False
    out = tool_named("browser_click").handler({"ref": 2, "double": True, "say": "Editing the row"}, ctx)
    assert ctx.pilot.done == ["click 130,210 left x2"]
    assert '[2] button "Save" in "Edit Work Order" @ 130,210' in out and not ctx.images


def test_a_write_is_blocked_while_changes_are_off(tmp_path):
    ctx = BrowserContext(tmp_path, effect=Effect.WRITE)
    with pytest.raises(ToolError, match="thread is Read-only"):
        tool_named("browser_click").handler({"ref": 2, "say": "Saving the work order"}, ctx)
    assert ctx.pilot.done == [] and ctx.asked == []


def test_a_write_waits_for_approval_when_changes_are_on(tmp_path):
    ctx = BrowserContext(tmp_path, write=True, effect=Effect.WRITE)
    tool_named("browser_click").handler({"ref": 2, "say": "Saving the work order"}, ctx)
    assert ctx.pilot.done == ["click 130,210 left x1"]
    assert 'left-click button "Save"' in ctx.asked[0]

    rejected = BrowserContext(tmp_path, write=True, approve="Reject", effect=Effect.WRITE)
    with pytest.raises(ToolError, match="rejected"):
        tool_named("browser_click").handler({"ref": 2, "say": "Saving the work order"}, rejected)
    assert rejected.pilot.done == []


def test_hover_scroll_and_press_in_are_not_judged(tmp_path):
    ctx = BrowserContext(tmp_path)
    tool_named("browser_hover").handler({"x": 5, "y": 6, "say": "Showing the tooltip"}, ctx)
    tool_named("browser_scroll").handler({"x": 5, "y": 6, "direction": "down", "say": "Scrolling the grid"}, ctx)
    tool_named("browser_mouse").handler({"x": 5, "y": 6, "action": "down", "say": "Holding"}, ctx)
    assert ctx.actions == []
    assert ctx.pilot.done == ["move 5,6", "scroll 5,6 0,600", "down 5,6"]

    tool_named("browser_mouse").handler({"x": 5, "y": 6, "action": "up", "say": "Letting go"}, ctx)
    assert len(ctx.actions) == 1 and "release the left mouse button" in ctx.actions[0]


def test_a_drag_is_judged_on_its_drop(tmp_path):
    ctx = BrowserContext(tmp_path)
    tool_named("browser_drag").handler({"from_x": 1, "from_y": 2, "to_ref": 2, "say": "Moving the row"}, ctx)
    assert ctx.pilot.done == ["drag 1,2 130,210"]
    assert 'drop it on button "Save"' in ctx.actions[0]


def test_typing_is_only_judged_when_it_submits(tmp_path):
    ctx = BrowserContext(tmp_path)
    tool_named("browser_type").handler({"ref": 1, "text": "WO-1", "clear": True, "say": "Searching"}, ctx)
    assert ctx.actions == [] and ctx.pilot.done == ["click 110,20 left x1", "type WO-1 (clear)"]

    tool_named("browser_type").handler({"text": "WO-2", "submit": True, "say": "Searching"}, ctx)
    assert len(ctx.actions) == 1 and ctx.pilot.done[-1] == "press Enter"


def test_moving_around_keys_are_not_judged(tmp_path):
    ctx = BrowserContext(tmp_path)
    tool_named("browser_press").handler({"key": "Escape", "say": "Closing the menu"}, ctx)
    tool_named("browser_press").handler({"key": "Enter", "say": "Confirming"}, ctx)
    assert len(ctx.actions) == 1 and "press Enter" in ctx.actions[0]


def test_a_target_needs_exactly_one_aim():
    with pytest.raises(BrowserError):
        Target()
    with pytest.raises(BrowserError):
        Target(ref=1, point=Point(1, 2))


def test_ov_changes_wait_for_the_ui_while_the_browser_is_open(tmp_path):
    from ov.agent.tools.onevizion import _write

    ctx = BrowserContext(tmp_path, write=True)
    with pytest.raises(ToolError, match="the browser is open"):
        _write("acme", "acme.onevizion.com", ["request", "PUT", "/v3/trackors/1"], ctx)
    assert ctx.asked == []


def test_sign_in_pages_are_recognised():
    assert browser._signed_out("https://acme.onevizion.com/Login.do?x=1")
    assert not browser._signed_out("https://acme.onevizion.com/Dashboard.do")


def test_a_run_stores_browser_events_and_forgets_them_on_reload(logged_in, monkeypatch):
    from helpers.agent import wait_done

    from ov.agent.engine.run import RunManager, runs
    from ov.agent.integrations.copilot import StreamResult
    from ov.agent.storage.models import Provider

    monkeypatch.setattr(
        "ov.agent.integrations.copilot.stream_chat", lambda *a, cancel, on_text, **_: StreamResult(text="ok")
    )
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    monkeypatch.setattr("ov.agent.integrations.copilot.complete", lambda *a, **k: ("Title", None))

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)
    run.emit({"type": "browser", "browser": {"open": True, "instance": "acme", "session": 1, "pointer": None}})
    run.emit({"type": "browser", "browser": {"pointer": {"x": 1, "y": 2, "step": 1}}})
    assert run.state["browser"] == {
        "open": True,
        "instance": "acme",
        "session": 1,
        "pointer": {"x": 1, "y": 2, "step": 1},
    }
    assert "browser" not in RunManager().get(run.id).state


def test_a_browser_that_dies_is_reported_closed_once():
    from ov.agent.engine.browsing import BrowserSlot, _Open

    class DeadPilot:
        failure = "The browser stopped: crashed"

    class StoppedScreen:
        def stop(self):
            pass

    events: list[dict] = []
    slot = BrowserSlot("r1", events.append)
    dead = DeadPilot()
    slot._open = _Open("acme", dead, StoppedScreen())
    slot.exited(dead)
    slot.exited(dead)
    closed = {"open": False, "dialog": None, "tabs": [], "error": "The browser stopped: crashed"}
    assert events == [{"type": "browser", "browser": closed}]
    assert not slot.live


def test_a_dialog_the_page_opens_is_reported_not_raised(tmp_path):
    ctx = BrowserContext(tmp_path)
    ctx.pilot.dialog = CONFIRM
    out = tool_named("browser_click").handler({"ref": 2, "say": "Deleting the record"}, ctx)
    assert 'showing a confirm: "Delete record 42?"' in out and "browser_dialog" in out


def test_accepting_a_confirm_is_a_checked_change(tmp_path):
    ctx = BrowserContext(tmp_path, effect=Effect.WRITE)
    ctx.pilot.dialog = CONFIRM
    with pytest.raises(ToolError, match="thread is Read-only"):
        tool_named("browser_dialog").handler({"action": "accept", "say": "Confirming"}, ctx)
    assert ctx.pilot.done == [] and 'press OK on the confirm "Delete record 42?"' in ctx.actions[0]

    tool_named("browser_dialog").handler({"action": "dismiss", "say": "Cancelling"}, ctx)
    assert ctx.pilot.done == ["dismiss"] and len(ctx.actions) == 1


def test_an_alert_is_accepted_without_a_check(tmp_path):
    ctx = BrowserContext(tmp_path, effect=Effect.WRITE)
    ctx.pilot.dialog = Dialog("alert", "Saved", "")
    out = tool_named("browser_dialog").handler({"action": "accept", "say": "Closing the alert"}, ctx)
    assert ctx.actions == [] and "Accepted the alert." in out


def test_answering_with_no_dialog_is_an_error(tmp_path):
    with pytest.raises(ToolError, match="No dialog"):
        tool_named("browser_dialog").handler({"action": "accept", "say": "OK"}, BrowserContext(tmp_path))


def test_popups_show_up_as_tabs(tmp_path):
    ctx = BrowserContext(tmp_path)
    ctx.vision = False
    ctx.pilot.tabs = [Tab(1, "Work Order", ctx.pilot.url, False), Tab(2, "Attachments", ctx.pilot.url, True)]
    out = tool_named("browser_tab").handler({"action": "switch", "index": 2, "say": "Showing the popup"}, ctx)
    assert ctx.pilot.done == ["switch 2"]
    assert "[2] Attachments | https://acme.onevizion.com/Dashboard.do (shown)" in out
