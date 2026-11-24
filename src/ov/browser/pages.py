from __future__ import annotations

from typing import Any

from playwright.sync_api import BrowserContext, Frame, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ov.browser.dialogs import Dialogs
from ov.browser.model import BrowserError, Tab

NAV_TIMEOUT_MS = 45_000
ANSWER_TIMEOUT_MS = 20_000
MS_PER_SECOND = 1000
CLICK_TIMEOUT_MS = 5_000
ACTION_PAUSE_MS = 150
IDLE_LOOP_MS = 40
SCREENSHOT_QUALITY = 70
NAVIGATED = ("Execution context was destroyed", "Cannot find context", "Frame was detached")
CLOSED = "The browser has closed."
ONLY_TAB = "This is the only tab; close the browser instead."
BUSY_PAGE = (
    "The page did not answer within {seconds}s: its scripts are still busy, which happens while the site is slow. "
    "Wait with browser_wait, then look again; opening the page again starts the slow load over."
)

Frames = tuple[Page, tuple[str, ...]]


def viewport(page: Page) -> dict[str, int]:
    size = page.viewport_size
    if size is None:
        raise BrowserError("The browser page has no screen size.")
    return size


def busy_page() -> BrowserError:
    return BrowserError(BUSY_PAGE.format(seconds=ANSWER_TIMEOUT_MS // MS_PER_SECOND))


def rest(page: Page, ms: float) -> None:
    try:
        page.wait_for_timeout(ms)
    except PlaywrightError:
        if not page.is_closed():
            raise


def evaluate(frame: Frame, script: str, arg: Any = None) -> Any:
    try:
        return frame.evaluate(script, arg)
    except PlaywrightError as exc:
        if not any(hint in str(exc) for hint in NAVIGATED):
            raise

    frame.page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
    return frame.evaluate(script, arg)


class Pages:
    def __init__(self, context: BrowserContext, size: dict[str, int], dialogs: Dialogs) -> None:
        self._context = context
        self._size = dict(size)
        self._dialogs = dialogs
        self._refs: set[str] = set()
        self._tabs: list[Page] = []
        self._active: Page | None = None
        self._targets: dict[Page, str] = {}
        self.changed = True

        context.on("page", self._track)

        for page in context.pages:
            self._track(page)

    @property
    def page(self) -> Page:
        if self._active is None:
            self._context.new_page()
        if self._active is None:
            raise BrowserError(CLOSED)
        return self._active

    def _track(self, page: Page) -> None:
        session = self._context.new_cdp_session(page)
        self._targets[page] = session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
        session.detach()

        self._tabs.append(page)
        self._active = page
        self.changed = True
        page.on("close", self._forget)
        page.on("load", self._loaded)
        page.on("dialog", self._dialogs.hold)
        if page.viewport_size != self._size:
            page.set_viewport_size(self._size)

    def _loaded(self, _: Page) -> None:
        self.changed = True

    def _forget(self, page: Page) -> None:
        self._tabs = [t for t in self._tabs if t is not page]
        self._targets.pop(page, None)
        self.changed = True

        if self._active is not page:
            return

        opener = page.opener()
        self._active = opener if opener in self._tabs else (self._tabs[-1] if self._tabs else None)

    def _tab(self, index: int) -> Page:
        if not 1 <= index <= len(self._tabs):
            raise BrowserError(f"There is no tab {index}; there are {len(self._tabs)}.")
        return self._tabs[index - 1]

    def tabs(self) -> list[Tab]:
        return [
            Tab(index, page.title(), page.url, page is self._active)
            for index, page in enumerate(self._tabs, start=1)
            if not page.is_closed()
        ]

    def switch(self, index: int) -> None:
        self._active = self._tab(index)
        self._refs = set()
        self._active.bring_to_front()
        self.changed = True

    def close_tab(self, index: int) -> None:
        if len(self._tabs) == 1:
            raise BrowserError(ONLY_TAB)
        self._tab(index).close()

    def active_target(self) -> str:
        return self._targets[self.page]

    def screenshot(self) -> bytes:
        try:
            return self.page.screenshot(type="jpeg", quality=SCREENSHOT_QUALITY, timeout=ANSWER_TIMEOUT_MS)
        except PlaywrightTimeout:
            raise busy_page() from None

    def where(self) -> tuple[str, str]:
        page = self.page
        return page.title(), page.url

    def resize(self, width: int, height: int) -> None:
        size = {"width": width, "height": height}
        if size == self._size:
            return

        self._size = size
        for page in self._tabs:
            if not page.is_closed():
                page.set_viewport_size(self._size)

    def idle(self) -> None:
        rest(self.page, IDLE_LOOP_MS)

    def after_dialog(self) -> None:
        self._after(self._frames())

    def _frames(self) -> Frames:
        page = self.page
        return page, tuple(f.url for f in page.frames if not f.is_detached())

    def _after(self, before: Frames) -> None:
        page, urls = before
        rest(page, ACTION_PAUSE_MS)
        if page.is_closed():
            return

        for frame in page.frames:
            if not frame.is_detached() and frame.url not in urls:
                frame.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
