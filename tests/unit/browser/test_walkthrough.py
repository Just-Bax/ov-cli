from __future__ import annotations

from pathlib import Path

from ov.browser.engine import ElementRef
from ov.browser.walkthrough import Action, Status, Walkthrough, hard_blocked, parse_action


class FakeBrowser:
    def __init__(self, elements: list[ElementRef], text: str = "") -> None:
        self._elements = elements
        self._text = text
        self.done: list[str] = []

    def snapshot(self):
        return self._elements

    def url(self):
        return "https://acme.test/page"

    def text(self):
        return self._text

    def goto(self, url):
        self.done.append(f"goto {url}")

    def click(self, target):
        self.done.append(f"click {target.name}")

    def fill(self, target, text):
        self.done.append(f"fill {target.name}={text}")

    def select(self, target, value):
        self.done.append(f"select {value}")

    def press(self, key):
        self.done.append(f"press {key}")

    def wait_for_text(self, text):
        self.done.append(f"wait {text}")

    def screenshot(self, path: Path):
        path.write_bytes(b"png")


class ScriptDriver:
    def __init__(self, actions: list[Action]) -> None:
        self._actions = iter(actions)

    def act(self, context):
        return next(self._actions)


class YesGuard:
    def allow(self, goal, action, element):
        return True, ""


class NoGuard:
    def allow(self, goal, action, element):
        return False, "not in scope"


def _run(browser, actions, guard, steps, tmp_path, *, goal="check the page"):
    walk = Walkthrough(browser, ScriptDriver(actions), guard, tmp_path, lambda: False)
    seen: list = []
    return walk.run(goal, steps, seen.append), seen


def test_a_passing_step_clicks_and_records_a_screenshot(tmp_path):
    browser = FakeBrowser([ElementRef(0, "button", "Save")])
    actions = [Action("click", index=0, reason="Save"), Action("pass", reason="saved")]
    results, _ = _run(browser, actions, YesGuard(), ["Save the form"], tmp_path)

    assert results[0].status == Status.PASSED
    assert browser.done == ["click Save"]
    assert (tmp_path / "step-1.png").exists() and results[0].screenshot == "step-1.png"


def test_assert_checks_the_page_text(tmp_path):
    browser = FakeBrowser([], text="Rule saved")
    results, _ = _run(browser, [Action("assert", text="Rule saved")], YesGuard(), ["See it saved"], tmp_path)
    assert results[0].status == Status.PASSED

    browser = FakeBrowser([], text="nothing")
    results, _ = _run(browser, [Action("assert", text="Rule saved")], YesGuard(), ["See it saved"], tmp_path)
    assert results[0].status == Status.FAILED


def test_a_destructive_click_is_blocked_without_the_fast_model(tmp_path):
    browser = FakeBrowser([ElementRef(0, "button", "Delete trackor")])
    actions = [Action("click", index=0, reason="remove it")]
    results, _ = _run(browser, actions, YesGuard(), ["open the trackor"], tmp_path)

    assert results[0].status == Status.BLOCKED
    assert "destructive" in results[0].detail
    assert browser.done == []


def test_the_fast_model_can_block_a_step(tmp_path):
    browser = FakeBrowser([ElementRef(0, "button", "Save")])
    results, _ = _run(browser, [Action("click", index=0)], NoGuard(), ["Save"], tmp_path)
    assert results[0].status == Status.BLOCKED and results[0].detail == "not in scope"


def test_a_destructive_step_is_allowed_when_the_goal_asks_for_it(tmp_path):
    browser = FakeBrowser([ElementRef(0, "button", "Delete trackor")])
    actions = [Action("click", index=0), Action("pass")]
    results, _ = _run(
        browser, actions, YesGuard(), ["delete the test trackor"], tmp_path, goal="delete the test trackor"
    )
    assert results[0].status == Status.PASSED


def test_parse_action_rejects_junk():
    assert parse_action('{"action": "click", "index": 2}').index == 2
    import pytest

    with pytest.raises(Exception, match="unknown action"):
        parse_action('{"action": "explode"}')
    with pytest.raises(Exception, match="needs an element index"):
        parse_action('{"action": "click"}')


def test_hard_blocked_only_fires_on_destructive_targets():
    assert hard_blocked("open it", Action("click", reason=""), "Save") is None
    assert hard_blocked("open it", Action("click"), "Delete") is not None
    assert hard_blocked("delete it", Action("click"), "Delete") is None
