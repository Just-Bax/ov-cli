from __future__ import annotations

from pathlib import Path

import pytest
from helpers.agent import FakeContext, wait_for

from ov.agent.engine.browsing import BrowserSlot
from ov.agent.engine.guard import Effect, Verdict
from ov.agent.instances.ovproc import find_instance
from ov.agent.storage import db
from ov.agent.tools import browser, tool_named
from ov.agent.tools.base import ToolError
from ov.browser.pilot import Aim, BrowserError, Dialog, DialogOpen, Point, Tab, Target, View

SAVE = Aim(Point(130, 210), 'button "Save" in "Edit Work Order" at (130, 210)', "button")
SEARCH = Aim(Point(110, 20), 'textbox "Search" at (110, 20)', "textbox")
CELL = Aim(Point(300, 400), 'gridcell "WO-1" at (300, 400)', "gridcell")
TREE = '- button "Save" [ref=e2]\n- textbox "Search" [ref=e1]'
CONFIRM = Dialog("confirm", "Delete record 42?", "")


class FakePilot:
    def __init__(self) -> None:
        self.done: list[str] = []
        self.url = "https://acme.onevizion.com/Dashboard.do"
        self.dialog: Dialog | None = None
        self.tabs_open = [Tab(1, "Work Order", self.url, True)]
        self.tree = TREE
        self.shots = 0
        self.fail_on = ""
        self.moves_to = ""

    def where(self):
        return "Work Order", self.url

    def tabs(self):
        return self.tabs_open

    def aim(self, target):
        if target.ref == "e2":
            return SAVE
        if target.ref == "e3":
            return CELL
        if target.point is not None:
            return Aim(target.point, f"clickable at ({target.point.x}, {target.point.y})", "clickable")
        return SEARCH

    def center(self):
        return Point(640, 400)

    def click(self, target, point, button, count, modifiers):
        if target.ref and target.ref == self.fail_on:
            raise BrowserError(f"{target.ref} is covered")
        self.done.append(f"click {point.x},{point.y} {button} x{count} {'+'.join(modifiers)}".strip())
        if self.dialog is not None:
            raise DialogOpen(self.dialog)
        if self.moves_to:
            self.url = self.moves_to

    def move(self, target, point):
        self.done.append(f"move {point.x},{point.y}")

    def press_mouse(self, point, button, down):
        self.done.append(f"{'down' if down else 'up'} {point.x},{point.y}")

    def drag(self, start, end):
        self.done.append(f"drag {start.x},{start.y} {end.x},{end.y}")

    def scroll(self, point, dx, dy):
        self.done.append(f"scroll {point.x},{point.y} {dx},{dy}")

    def type(self, target, point, text, clear):
        into = f"at {point.x},{point.y} " if point else ""
        self.done.append(f"type {into}{text}{' (clear)' if clear else ''}")

    def press(self, key):
        self.done.append(f"press {key}")

    def pause(self, seconds):
        self.done.append(f"pause {seconds:g}")

    def select(self, target, option):
        self.done.append(f"select {option}")

    def upload(self, target, point, paths):
        self.done.append("upload " + ", ".join(Path(p).name for p in paths))

    def snapshot(self):
        return View(self.url, "Work Order", 1280, 800, False, self.tabs_open, self.tree)

    def screenshot(self):
        self.shots += 1
        return b"jpeg"

    def take_blocked(self):
        return []


class FakeSlot:
    live = True

    def __init__(self, pilot: FakePilot) -> None:
        self._pilot = pilot
        self.pointers: list[tuple[Point, bool]] = []
        self._loops = BrowserSlot("r1", lambda _: None)

    def pilot(self):
        return self._pilot

    def pointer(self, point, press):
        self.pointers.append((point, press))

    def looping(self, action):
        return self._loops.looping(action)

    def saw(self, page):
        self._loops.saw(page)

    def answer_dialog(self, accept, text):
        self._pilot.done.append(f"{'accept' if accept else 'dismiss'} {text}".strip())
        self._pilot.dialog = None

    def switch_tab(self, index):
        self._pilot.done.append(f"switch {index}")


class BrowserContext(FakeContext):
    def __init__(self, tmp_path, write=False, approve="Approve", effect=Effect.READ, full=False):
        super().__init__(tmp_path, write=write, approve=approve, full=full)
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


def test_a_click_moves_the_cursor_and_returns_only_where_it_landed(tmp_path):
    ctx = BrowserContext(tmp_path)
    out = tool_named("browser_click").handler({"ref": "e2", "say": "Saving"}, ctx)
    assert ctx.pilot.done == ["click 130,210 left x1"] and ctx.asked == []
    assert ctx.browser.pointers == [(Point(130, 210), True)]
    assert out == f"Did left-click on {SAVE.label}.\nNow: Work Order | {ctx.pilot.url}"
    assert not ctx.images and ctx.pilot.shots == 0
    assert ctx.actions == [f"<action>left-click {SAVE.label}</action>\n<page>Work Order | /Dashboard.do</page>"]


def test_a_snapshot_lists_refs_and_attaches_a_screenshot_only_on_request(tmp_path):
    ctx = BrowserContext(tmp_path)
    out = tool_named("browser_snapshot").handler({}, ctx)
    assert '- button "Save" [ref=e2]' in out and not ctx.images
    out = tool_named("browser_snapshot").handler({"screenshot": True}, ctx)
    assert len(ctx.images) == 1 and "Screenshot attached: 1280x800" in out


def test_clicking_a_field_or_a_tab_is_not_judged(tmp_path):
    ctx = BrowserContext(tmp_path, effect=Effect.WRITE)
    tool_named("browser_click").handler({"ref": "e1", "say": "Focusing the search"}, ctx)
    assert ctx.actions == [] and ctx.pilot.done == ["click 110,20 left x1"]


def test_a_grid_cell_click_or_a_delete_key_is_judged_like_any_change(tmp_path):
    ctx = BrowserContext(tmp_path, effect=Effect.WRITE)
    with pytest.raises(ToolError, match="Read-only"):
        tool_named("browser_click").handler({"ref": "e3", "say": "Opening the row"}, ctx)
    with pytest.raises(ToolError, match="Read-only"):
        tool_named("browser_press").handler({"key": "Delete", "say": "Clearing"}, ctx)
    assert ctx.pilot.done == []


def test_full_access_never_asks_the_guard(tmp_path):
    ctx = BrowserContext(tmp_path, effect=Effect.WRITE, full=True)
    tool_named("browser_click").handler({"ref": "e2", "say": "Saving"}, ctx)
    assert ctx.actions == [] and ctx.asked == []


def test_the_same_action_over_and_over_is_stopped(tmp_path):
    ctx = BrowserContext(tmp_path)
    for say in ("Saving", "Saving again", "Saving once more"):
        tool_named("browser_click").handler({"ref": "e2", "say": say}, ctx)
    with pytest.raises(ToolError, match="4 times in a row"):
        tool_named("browser_click").handler({"ref": "e2", "say": "Saving"}, ctx)

    tool_named("browser_click").handler({"ref": "e1", "say": "Focusing the search"}, ctx)
    assert len(ctx.pilot.done) == 4


def test_a_write_is_blocked_while_changes_are_off(tmp_path):
    ctx = BrowserContext(tmp_path, effect=Effect.WRITE)
    with pytest.raises(ToolError, match="thread is Read-only"):
        tool_named("browser_click").handler({"ref": "e2", "say": "Saving the work order"}, ctx)
    assert ctx.pilot.done == [] and ctx.asked == []


def test_a_write_waits_for_approval_when_changes_are_on(tmp_path):
    ctx = BrowserContext(tmp_path, write=True, effect=Effect.WRITE)
    tool_named("browser_click").handler({"ref": "e2", "say": "Saving the work order"}, ctx)
    assert ctx.pilot.done == ["click 130,210 left x1"]
    assert 'left-click button "Save"' in ctx.asked[0]

    rejected = BrowserContext(tmp_path, write=True, approve="Reject", effect=Effect.WRITE)
    with pytest.raises(ToolError, match="rejected"):
        tool_named("browser_click").handler({"ref": "e2", "say": "Saving the work order"}, rejected)
    assert rejected.pilot.done == []


def test_hover_scroll_and_press_in_are_not_judged(tmp_path):
    ctx = BrowserContext(tmp_path)
    tool_named("browser_hover").handler({"x": 5, "y": 6, "say": "Showing the tooltip"}, ctx)
    tool_named("browser_scroll").handler({"x": 5, "y": 6, "direction": "down", "say": "Scrolling the grid"}, ctx)
    tool_named("browser_scroll").handler({"direction": "up", "say": "Scrolling the page"}, ctx)
    tool_named("browser_mouse").handler({"x": 5, "y": 6, "action": "down", "say": "Holding"}, ctx)
    assert ctx.actions == []
    assert ctx.pilot.done == ["move 5,6", "scroll 5,6 0,600", "scroll 640,400 0,-600", "down 5,6"]

    tool_named("browser_mouse").handler({"x": 5, "y": 6, "action": "up", "say": "Letting go"}, ctx)
    assert len(ctx.actions) == 1 and "release the left mouse button" in ctx.actions[0]


def test_a_drag_is_judged_on_its_drop(tmp_path):
    ctx = BrowserContext(tmp_path)
    tool_named("browser_drag").handler({"from_x": 1, "from_y": 2, "to_ref": "e2", "say": "Moving the row"}, ctx)
    assert ctx.pilot.done == ["drag 1,2 130,210"]
    assert 'drop it on button "Save"' in ctx.actions[0]


def test_typing_is_only_judged_when_it_submits(tmp_path):
    ctx = BrowserContext(tmp_path)
    tool_named("browser_type").handler({"ref": "e1", "text": "WO-1", "clear": True, "say": "Searching"}, ctx)
    assert ctx.actions == [] and ctx.pilot.done == ["type at 110,20 WO-1 (clear)"]
    tool_named("browser_type").handler({"text": "WO-2", "submit": True, "say": "Searching"}, ctx)
    assert len(ctx.actions) == 1 and ctx.pilot.done[-2:] == ["type WO-2", "press Enter"]


def test_moving_around_keys_are_not_judged(tmp_path):
    ctx = BrowserContext(tmp_path)
    tool_named("browser_press").handler({"key": "Escape", "say": "Closing the menu"}, ctx)
    tool_named("browser_press").handler({"key": "Enter", "say": "Confirming"}, ctx)
    assert len(ctx.actions) == 1 and "press Enter" in ctx.actions[0]


def test_a_target_needs_exactly_one_aim():
    with pytest.raises(BrowserError):
        Target()
    with pytest.raises(BrowserError):
        Target(ref="e1", point=Point(1, 2))


def test_ov_changes_wait_for_the_ui_while_the_browser_is_open(tmp_path):
    from ov.agent.tools.onevizion import _write

    ctx = BrowserContext(tmp_path, write=True)
    with pytest.raises(ToolError, match="the browser is open"):
        _write("acme", "acme.onevizion.com", ["request", "PUT", "/v3/trackors/1"], ctx)
    assert ctx.asked == []


def test_sign_in_pages_are_recognised():
    host = "acme.onevizion.com"
    assert browser._signed_out("https://acme.onevizion.com/Login.do?x=1", host)
    assert browser._signed_out("https://login.microsoftonline.com/common/oauth2/authorize", host)
    assert not browser._signed_out("https://acme.onevizion.com/Dashboard.do", host)


def test_a_run_stores_browser_events_and_forgets_them_on_reload(logged_in, monkeypatch):
    from helpers.agent import wait_done

    from ov.agent.engine.run_manager import RunManager, runs
    from ov.agent.integrations.copilot import StreamResult

    monkeypatch.setattr(
        "ov.agent.integrations.copilot.stream_chat", lambda *a, cancel, on_text, **_: StreamResult(text="ok")
    )
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    monkeypatch.setattr("ov.agent.integrations.copilot.complete", lambda *a, **k: ('{"title": "Title"}', None))

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, "copilot", "test-model")
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
    from ov.agent.engine.browsing import _Open

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
    out = tool_named("browser_click").handler({"ref": "e2", "say": "Deleting the record"}, ctx)
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
    ctx.pilot.tabs_open = [Tab(1, "Work Order", ctx.pilot.url, False), Tab(2, "Attachments", ctx.pilot.url, True)]
    out = tool_named("browser_tab").handler({"action": "switch", "index": 2, "say": "Showing the popup"}, ctx)
    assert ctx.pilot.done == ["switch 2"]
    assert "[2] Attachments | https://acme.onevizion.com/Dashboard.do (shown)" in out


def _steps(ctx, *steps, say="Filling the form"):
    return tool_named("browser_steps").handler({"steps": list(steps), "say": say}, ctx)


def test_steps_run_in_one_call_and_each_change_is_checked_on_its_own(tmp_path):
    ctx = BrowserContext(tmp_path, write=True, effect=Effect.WRITE)
    out = _steps(
        ctx,
        {"action": "type", "ref": "e1", "text": "WO-1", "clear": True},
        {"action": "select", "ref": "e1", "option": "Staged"},
        {"action": "click", "ref": "e2", "say": "Saving"},
    )
    assert ctx.pilot.done == ["type at 110,20 WO-1 (clear)", "select Staged", "click 130,210 left x1"]
    assert [a.split("</action>")[0] for a in ctx.actions] == [
        f'<action>choose "Staged" in {SEARCH.label}',
        f"<action>left-click {SAVE.label}",
    ]
    assert len(ctx.asked) == 2 and ctx.asked[0].startswith('choose "Staged"') and "left-click" in ctx.asked[1]
    assert out.splitlines()[:3] == [
        f"1. Typed into {SEARCH.label}.",
        f'2. Chose "Staged" in {SEARCH.label}.',
        f"3. Did left-click on {SAVE.label}.",
    ]
    assert out.endswith(f"Now: Work Order | {ctx.pilot.url}")


def test_steps_stop_at_the_first_failure_and_say_what_ran(tmp_path):
    ctx = BrowserContext(tmp_path)
    ctx.pilot.fail_on = "e2"
    out = _steps(
        ctx,
        {"action": "type", "ref": "e1", "text": "WO-1"},
        {"action": "click", "ref": "e2"},
        {"action": "press", "key": "Tab"},
    )
    assert ctx.pilot.done == ["type at 110,20 WO-1"]
    assert "Stopped at step 2 of 3: e2 is covered" in out and "3." not in out

    first = BrowserContext(tmp_path)
    first.pilot.fail_on = "e2"
    with pytest.raises(BrowserError, match="covered"):
        _steps(first, {"action": "click", "ref": "e2"})


def test_a_rejected_change_ends_the_steps(tmp_path):
    ctx = BrowserContext(tmp_path, write=True, approve="Reject", effect=Effect.WRITE)
    out = _steps(
        ctx,
        {"action": "type", "ref": "e1", "text": "WO-1"},
        {"action": "click", "ref": "e2"},
        {"action": "press", "key": "Tab"},
    )
    assert ctx.pilot.done == ["type at 110,20 WO-1"]
    assert "Stopped at step 2 of 3: The user rejected this" in out


def test_steps_stop_when_the_page_goes_elsewhere(tmp_path):
    ctx = BrowserContext(tmp_path)
    ctx.pilot.moves_to = "https://acme.onevizion.com/Other.do"
    out = _steps(
        ctx, {"action": "click", "ref": "e1"}, {"action": "type", "text": "x"}, {"action": "press", "key": "Tab"}
    )
    assert ctx.pilot.done == ["click 110,20 left x1"]
    assert "after step 1, so the last 2 step(s) did not run" in out
    assert out.endswith("Now: Work Order | https://acme.onevizion.com/Other.do")


def test_a_dialog_during_steps_keeps_what_ran(tmp_path):
    ctx = BrowserContext(tmp_path)
    ctx.pilot.dialog = CONFIRM
    out = _steps(
        ctx,
        {"action": "type", "ref": "e1", "text": "WO-1"},
        {"action": "click", "ref": "e2"},
        {"action": "press", "key": "Tab"},
    )
    assert out.splitlines()[0] == f"1. Typed into {SEARCH.label}."
    assert 'showing a confirm: "Delete record 42?"' in out and "press Tab" not in ctx.pilot.done


@pytest.mark.parametrize(
    ("steps", "error"),
    [
        ([], "at least one step"),
        ([{"action": "press", "key": "Tab"}] * 13, "at most 12 steps"),
        ([{"action": "drag"}], "'drag' is not a step"),
        ([{"action": "type", "text": "a"}, {"action": "click"}], r"Step 2 \(click\) needs one of ref"),
        ([{"action": "select", "ref": "e1"}], r"Step 1 \(select\) needs option"),
    ],
)
def test_bad_steps_are_refused_before_anything_runs(tmp_path, steps, error):
    ctx = BrowserContext(tmp_path)
    with pytest.raises(ToolError, match=error):
        _steps(ctx, *steps)
    assert ctx.pilot.done == []


def test_an_upload_takes_files_of_the_run_and_is_checked(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"pdf")
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "photo.png").write_bytes(b"png")
    ctx = BrowserContext(tmp_path, write=True, effect=Effect.WRITE)
    out = tool_named("browser_upload").handler(
        {"ref": "e2", "files": ["report.pdf", "photo.png"], "say": "Uploading"}, ctx
    )
    assert ctx.pilot.done == ["upload report.pdf, photo.png"]
    assert f"upload report.pdf, photo.png with {SAVE.label}" in ctx.actions[0]
    assert len(ctx.asked) == 1 and ctx.asked[0].startswith("upload report.pdf")
    assert out.startswith(f"Uploaded report.pdf, photo.png with {SAVE.label}.")


@pytest.mark.parametrize(
    ("name", "error"), [("../secret.txt", "outside the run folder"), ("missing.pdf", "No file missing.pdf")]
)
def test_an_upload_refuses_files_outside_the_run(tmp_path, name, error):
    run = tmp_path / "run"
    run.mkdir()
    (tmp_path / "secret.txt").write_text("x")
    ctx = BrowserContext(run, full=True)
    with pytest.raises(ToolError, match=error):
        tool_named("browser_upload").handler({"ref": "e2", "files": [name], "say": "Uploading"}, ctx)
    assert ctx.pilot.done == []


def test_going_back_and_forth_without_looking_is_stopped(tmp_path):
    ctx = BrowserContext(tmp_path)
    click = tool_named("browser_click").handler
    for _ in range(3):
        click({"ref": "e1", "say": "Opening"}, ctx)
        click({"ref": "e2", "say": "Closing"}, ctx)
    with pytest.raises(ToolError, match="went round the same 2 steps"):
        click({"ref": "e1", "say": "Opening"}, ctx)


def test_the_same_click_on_a_page_that_changes_is_not_a_loop(tmp_path):
    ctx = BrowserContext(tmp_path)
    for page in range(6):
        ctx.pilot.tree = f'- button "Next" [ref=e2]\n- text "Page {page}"'
        tool_named("browser_snapshot").handler({}, ctx)
        tool_named("browser_click").handler({"ref": "e2", "say": "Next page"}, ctx)
    assert len(ctx.pilot.done) == 6


def test_looking_at_the_same_page_again_and_again_is_stopped(tmp_path):
    ctx = BrowserContext(tmp_path)
    for _ in range(3):
        tool_named("browser_snapshot").handler({}, ctx)
        tool_named("browser_wait").handler({"seconds": 1, "say": "Waiting"}, ctx)
    with pytest.raises(ToolError, match="last 4 snapshots showed the same page"):
        tool_named("browser_snapshot").handler({}, ctx)


def test_opening_the_browser_on_an_ended_web_session_asks_to_sign_in_first(logged_in, monkeypatch):
    from ov.agent.engine.run import Run
    from ov.agent.engine.run_manager import runs
    from ov.agent.storage.models import Access

    asked: list[tuple[str, bool]] = []
    shown: list[str] = []
    monkeypatch.setattr("ov.agent.engine.run_browser.web_session_alive", lambda alias: False)
    monkeypatch.setattr(
        Run, "require_login", lambda self, host, tenant="", web=False: asked.append((host, web)) or True
    )
    monkeypatch.setattr(Run, "_show_browser", lambda self, found: shown.append(found["alias"]))
    db.create_thread("rbrowse", "Browse", "copilot", "m", instance="acme", access=Access.READ)

    runs.get("rbrowse").open_browser("acme")
    wait_for(lambda: shown)

    assert asked == [(find_instance("acme")["host"], True)] and shown == ["acme"]
