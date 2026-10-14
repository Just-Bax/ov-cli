from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Browser, BrowserContext, Page, Playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

LAUNCH_ARGS = ["--no-first-run", "--no-default-browser-check"]
DEFAULT_TIMEOUT_MS = 15_000
NAV_TIMEOUT_MS = 30_000
SNAPSHOT_LIMIT = 60
NAME_CHARS = 80
TEXT_CHARS = 6_000
INTERACTIVE = "a, button, input, textarea, select, [role=button], [role=link], [role=tab], [role=menuitem]"


class BrowserError(Exception):
    pass


@dataclass
class ElementRef:
    index: int
    role: str
    name: str


def chromium(playwright: Playwright, *, headless: bool, debug_port: int | None) -> Browser:
    args = [*LAUNCH_ARGS]
    if debug_port is not None:
        args.append(f"--remote-debugging-port={debug_port}")
    try:
        return playwright.chromium.launch(headless=headless, args=args)
    except PlaywrightError as exc:
        raise BrowserError(f"Could not start the browser: {exc}") from exc


def _cookies_for(base_url: str, cookies: dict[str, str]) -> list[dict[str, Any]]:
    host = urlsplit(base_url).netloc
    return [{"name": name, "value": value, "domain": host, "path": "/"} for name, value in cookies.items()]


class Session:
    def __init__(self, browser: Browser, base_url: str, cookies: dict[str, str], width: int, height: int) -> None:
        self._context: BrowserContext = browser.new_context(viewport={"width": width, "height": height})
        self._context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        if cookies:
            self._context.add_cookies(_cookies_for(base_url, cookies))
        self.page: Page = self._context.new_page()

    def close(self) -> None:
        self._context.close()

    def goto(self, url: str) -> None:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except PlaywrightTimeout:
            raise BrowserError(f"Timed out loading {url}.") from None

    def _locator(self, target: ElementRef) -> Any:
        found = self.page.locator(INTERACTIVE).nth(target.index)
        if found.count() == 0:
            raise BrowserError(f"Element {target.index} ({target.name}) is no longer on the page.")
        return found

    def click(self, target: ElementRef) -> None:
        self._act(lambda: self._locator(target).click(), f"click {target.name}")

    def fill(self, target: ElementRef, text: str) -> None:
        self._act(lambda: self._locator(target).fill(text), f"type into {target.name}")

    def press(self, key: str) -> None:
        self._act(lambda: self.page.keyboard.press(key), f"press {key}")

    def select(self, target: ElementRef, value: str) -> None:
        self._act(lambda: self._locator(target).select_option(label=value), f"choose {value}")

    def wait_for_text(self, text: str) -> None:
        try:
            self.page.get_by_text(text, exact=False).first.wait_for(state="visible")
        except PlaywrightTimeout:
            raise BrowserError(f'Never saw "{text}" on the page.') from None

    def _act(self, run: Any, label: str) -> None:
        try:
            run()
        except PlaywrightTimeout:
            raise BrowserError(f"Could not {label}: the element did not respond in time.") from None
        except PlaywrightError as exc:
            raise BrowserError(f"Could not {label}: {_first_line(exc)}") from None

    def url(self) -> str:
        return self.page.url

    def text(self) -> str:
        body = self.page.inner_text("body")
        return body[:TEXT_CHARS]

    def snapshot(self) -> list[ElementRef]:
        handles = self.page.locator(INTERACTIVE)
        refs: list[ElementRef] = []
        for index in range(min(handles.count(), SNAPSHOT_LIMIT)):
            element = handles.nth(index)
            name = (
                element.get_attribute("aria-label") or element.inner_text() or element.get_attribute("name") or ""
            ).strip()
            refs.append(ElementRef(index=index, role=_role_of(element), name=" ".join(name.split())[:NAME_CHARS]))
        return refs

    def screenshot(self, path: Path) -> None:
        self.page.screenshot(path=str(path), full_page=False)


def _role_of(element: Any) -> str:
    explicit = element.get_attribute("role")
    if explicit:
        return explicit
    return (element.evaluate("e => e.tagName") or "").lower()


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__
