from __future__ import annotations

import re
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ov.browser.model import Aim, BrowserError, Element, Point, Target, View
from ov.browser.pages import (
    ANSWER_TIMEOUT_MS,
    CLICK_TIMEOUT_MS,
    MS_PER_SECOND,
    NAV_TIMEOUT_MS,
    NAVIGATED,
    Pages,
    busy_page,
    evaluate,
    rest,
    viewport,
)
from ov.browser.scripts import ELEMENT_SCRIPT, POINT_SCRIPT, READY_SCRIPT, TEXT_SCRIPT

WAIT_POLL_MS = 250
MAX_WAIT_SECONDS = 30
NAME_CHARS = 80
VALUE_CHARS = 80
TREE_CHARS = 12_000
SNAPSHOT_MODE = "ai"
LOADED = "complete"
REF_PATTERN = re.compile(r"\[ref=(\w+)\]")
UNKNOWN_REF = "There is no {ref} in the last snapshot. Take a new snapshot and use its refs."
GONE_REF = "{ref} is no longer on the page. Take a new snapshot."
NO_BOX = "{target} is not visible on the page. Scroll to it or take a new snapshot."
TREE_CUT = "[{chars} more chars cut. Scroll, or wait or aim with a locator for what you need.]"


def _inside(box: dict[str, float], point: Point) -> bool:
    return box["x"] <= point.x <= box["x"] + box["width"] and box["y"] <= point.y <= box["y"] + box["height"]


class Reader(Pages):
    def snapshot(self) -> View:
        page = self.page
        url = page.url
        tree = self._tree(page)
        if page.url != url:
            page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
            tree = self._tree(page)

        self._refs = set(REF_PATTERN.findall(tree))
        size = viewport(page)
        loading = evaluate(page.main_frame, READY_SCRIPT) != LOADED

        extra = len(tree) - TREE_CHARS
        if extra > 0:
            tree = f"{tree[:TREE_CHARS]}\n{TREE_CUT.format(chars=extra)}"
        return View(page.url, page.title(), size["width"], size["height"], loading, self.tabs(), tree)

    def _tree(self, page: Page) -> str:
        try:
            return self._aria(page)
        except PlaywrightError as exc:
            if not any(hint in str(exc) for hint in NAVIGATED):
                raise

        page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
        return self._aria(page)

    def _aria(self, page: Page) -> str:
        try:
            return page.aria_snapshot(mode=SNAPSHOT_MODE, timeout=ANSWER_TIMEOUT_MS)
        except PlaywrightTimeout:
            raise busy_page() from None

    def _ref_locator(self, ref: str) -> Locator:
        if ref not in self._refs:
            raise BrowserError(UNKNOWN_REF.format(ref=ref))
        found = self.page.locator(f"aria-ref={ref}")
        if found.count() == 0:
            raise BrowserError(GONE_REF.format(ref=ref))
        return found

    def _selector_locator(self, selector: str) -> Locator:
        for frame in self.page.frames:
            if frame.is_detached():
                continue
            found = frame.locator(selector)
            if found.count() > 0:
                return found.first

        raise BrowserError(f"Nothing on the page matches {selector}.")

    def _locator(self, target: Target) -> Locator:
        if target.ref:
            return self._ref_locator(target.ref)
        return self._selector_locator(target.locator or "")

    def aim(self, target: Target) -> Aim:
        if target.point is not None:
            return self.describe_at(target.point)

        found = self._locator(target)
        found.scroll_into_view_if_needed(timeout=CLICK_TIMEOUT_MS)
        box = found.bounding_box()
        if box is None:
            raise BrowserError(NO_BOX.format(target=target.ref or target.locator))

        point = Point(round(box["x"] + box["width"] / 2), round(box["y"] + box["height"] / 2))
        args = {"x": point.x, "y": point.y, "nameChars": NAME_CHARS, "valueChars": VALUE_CHARS}
        element = Element(**found.evaluate(ELEMENT_SCRIPT, args))
        return Aim(point, f"{element.describe()} at ({point.x}, {point.y})", element.role)

    def describe_at(self, point: Point) -> Aim:
        page = self.page
        size = viewport(page)
        if not (0 <= point.x < size["width"] and 0 <= point.y < size["height"]):
            raise BrowserError(f"({point.x}, {point.y}) is outside the {size['width']}x{size['height']} screen.")

        frame, offset, area = page.main_frame, Point(0, 0), float("inf")
        for child in page.frames:
            if child.parent_frame is None or child.is_detached():
                continue
            box = child.frame_element().bounding_box()
            if box is not None and _inside(box, point) and box["width"] * box["height"] < area:
                frame, offset, area = child, Point(box["x"], box["y"]), box["width"] * box["height"]

        found = evaluate(
            frame,
            POINT_SCRIPT,
            {"x": point.x - offset.x, "y": point.y - offset.y, "nameChars": NAME_CHARS, "valueChars": VALUE_CHARS},
        )
        if found is None:
            return Aim(point, f"empty space at ({point.x}, {point.y})", "")

        element = Element(**found)
        return Aim(point, f"{element.describe()} at ({point.x}, {point.y})", element.role)

    def center(self) -> Point:
        size = viewport(self.page)
        return Point(size["width"] // 2, size["height"] // 2)

    def pause(self, seconds: float) -> None:
        rest(self.page, min(seconds, MAX_WAIT_SECONDS) * MS_PER_SECOND)

    def wait_for(self, text: str, selector: str, url_part: str, seconds: float) -> None:
        deadline = time.monotonic() + min(seconds, MAX_WAIT_SECONDS)
        while True:
            page = self.page
            if self._matches(page, text, selector, url_part):
                return

            if time.monotonic() > deadline:
                raise BrowserError(f"Waited {seconds:g}s and the page still does not show it.")

            rest(page, WAIT_POLL_MS)

    def _matches(self, page: Page, text: str, selector: str, url_part: str) -> bool:
        if url_part and url_part not in page.url:
            return False
        frames = [f for f in page.frames if not f.is_detached()]
        if text and not any(text in evaluate(f, TEXT_SCRIPT) for f in frames):
            return False
        return not selector or any(f.locator(selector).count() > 0 for f in frames)
