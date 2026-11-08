from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ov.browser.model import BUTTONS, BrowserError, Point, Target, timeout_reason
from ov.browser.pages import ACTION_PAUSE_MS, CLICK_TIMEOUT_MS
from ov.browser.reader import Reader

MOVE_STEPS = 8
DRAG_STEPS = 16
SELECT_ALL_KEY = "ControlOrMeta+A"
ERASE_KEY = "Backspace"
NOT_SELECT = "That is not a standard dropdown: click it open and click the option instead."
NOT_SELECT_HINT = "not a <select>"
NO_FILE_PICKER = "Clicking that did not open a file picker. Aim at the upload button or file field of the page."


class Hands(Reader):
    def move(self, target: Target, point: Point) -> None:
        before = self._frames()
        if target.point is None:
            self._locator(target).hover(timeout=CLICK_TIMEOUT_MS)
        else:
            self.page.mouse.move(point.x, point.y, steps=MOVE_STEPS)
        self._after(before)

    def click(self, target: Target, point: Point, button: str, count: int, modifiers: list[str]) -> None:
        before = self._frames()
        self._click(target, point, button, count, modifiers)
        self._after(before)

    def _click(self, target: Target, point: Point, button: str, count: int, modifiers: list[str]) -> None:
        if target.point is None:
            self._locator(target).click(button=button, click_count=count, modifiers=modifiers, timeout=CLICK_TIMEOUT_MS)
            return

        page = self.page
        page.mouse.move(point.x, point.y, steps=MOVE_STEPS)
        for key in modifiers:
            page.keyboard.down(key)

        page.mouse.click(point.x, point.y, button=button, click_count=count)

        for key in reversed(modifiers):
            page.keyboard.up(key)

    def press_mouse(self, point: Point, button: str, down: bool) -> None:
        page = self.page
        before = self._frames()
        page.mouse.move(point.x, point.y, steps=MOVE_STEPS)
        if down:
            page.mouse.down(button=button)
        else:
            page.mouse.up(button=button)

        self._after(before)

    def drag(self, start: Point, end: Point) -> None:
        page = self.page
        before = self._frames()
        page.mouse.move(start.x, start.y, steps=MOVE_STEPS)
        page.mouse.down()
        page.mouse.move(end.x, end.y, steps=DRAG_STEPS)
        page.mouse.up()

        self._after(before)

    def scroll(self, point: Point, dx: int, dy: int) -> None:
        page = self.page
        page.mouse.move(point.x, point.y)
        page.mouse.wheel(dx, dy)
        page.wait_for_timeout(ACTION_PAUSE_MS)

    def type(self, target: Target | None, point: Point | None, text: str, clear: bool) -> None:
        page = self.page
        before = self._frames()
        if target is not None and point is not None:
            self._click(target, point, BUTTONS[0], 1, [])

        if clear:
            page.keyboard.press(SELECT_ALL_KEY)
            page.keyboard.press(ERASE_KEY)

        page.keyboard.type(text)
        self._after(before)

    def press(self, key: str) -> None:
        before = self._frames()
        self.page.keyboard.press(key)
        self._after(before)

    def select(self, target: Target, option: str) -> None:
        before = self._frames()
        try:
            self._locator(target).select_option(label=option, timeout=CLICK_TIMEOUT_MS)
        except PlaywrightError as exc:
            if NOT_SELECT_HINT in str(exc):
                raise BrowserError(NOT_SELECT) from None
            raise

        self._after(before)

    def upload(self, target: Target, point: Point, paths: list[str]) -> None:
        page = self.page
        before = self._frames()
        try:
            with page.expect_file_chooser(timeout=CLICK_TIMEOUT_MS) as chooser:
                self._open_picker(target, point)
        except PlaywrightTimeout:
            raise BrowserError(NO_FILE_PICKER) from None

        chooser.value.set_files(paths)
        self._after(before)

    def _open_picker(self, target: Target, point: Point) -> None:
        try:
            self._click(target, point, BUTTONS[0], 1, [])
        except PlaywrightTimeout as exc:
            raise BrowserError(timeout_reason(exc)) from None
