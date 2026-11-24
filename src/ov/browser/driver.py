from __future__ import annotations

from playwright.sync_api import BrowserContext
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ov.browser.dialogs import Dialogs
from ov.browser.fence import Allows, Fence
from ov.browser.hands import Hands
from ov.browser.model import BrowserError
from ov.browser.pages import MS_PER_SECOND, NAV_TIMEOUT_MS

CSRF_SCRIPT = "() => document.querySelector('meta[name=_csrf]')?.getAttribute('content') || ''"
NO_CSRF = "Open a OneVizion page of the instance first; the preview takes its session from that page."
SLOW_PAGE = "{url} did not load within {seconds}s; the site is slow right now. It may still finish: look again shortly."


class Driver(Hands):
    def __init__(
        self, context: BrowserContext, hostname: str, size: dict[str, int], dialogs: Dialogs, allows: Allows
    ) -> None:
        self._hostname = hostname
        self._fence = Fence(context, allows)
        super().__init__(context, size, dialogs)

    def add_cookies(self, cookies: dict[str, str]) -> None:
        self._context.add_cookies(
            [{"name": name, "value": value, "domain": self._hostname, "path": "/"} for name, value in cookies.items()]
        )

    def preview(self, name: str, page: str) -> str:
        csrf = self.page.evaluate(CSRF_SCRIPT)
        if not csrf:
            raise BrowserError(NO_CSRF)
        return self._fence.preview(name, page, csrf)

    def goto(self, url: str) -> None:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except PlaywrightTimeout:
            raise BrowserError(SLOW_PAGE.format(url=url, seconds=NAV_TIMEOUT_MS // MS_PER_SECOND)) from None
        self._refs = set()
