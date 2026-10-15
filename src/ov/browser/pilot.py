from __future__ import annotations

import queue
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Frame, Locator, Page, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ov.onevizion.login import SCREEN_CHANNEL, browser_is_installed, desktop_user_agent

LAUNCH_ARGS = ["--no-first-run", "--no-default-browser-check"]
ACTION_TIMEOUT_MS = 15_000
NAV_TIMEOUT_MS = 45_000
ACTION_PAUSE_MS = 250
SETTLE_POLL_MS = 250
ACTION_SETTLE_SECONDS = 3
PAGE_SETTLE_SECONDS = 10
WAIT_POLL_MS = 250
MAX_WAIT_SECONDS = 30
IDLE_LOOP_MS = 40
MOVE_STEPS = 8
DRAG_STEPS = 16
SELECT_ALL_KEY = "ControlOrMeta+A"
ERASE_KEY = "Backspace"
START_TIMEOUT_SECONDS = 90
CALL_TIMEOUT_SECONDS = 120
CALL_POLL_SECONDS = 0.5
MAX_ELEMENTS = 200
NAME_CHARS = 80
VALUE_CHARS = 80
TEXT_CHARS = 8_000
SCREENSHOT_QUALITY = 70
REF_ATTRIBUTE = "data-ov-ref"
BLANK_PAGE = "about:blank"
STAY_PUT_STATUS = 204
EVERY_REQUEST = "**/*"
NOT_INSTALLED = "The browser is not installed. Run: ov setup"
CLOSED = "The browser has closed."
NAVIGATED = ("Execution context was destroyed", "Cannot find context", "Frame was detached")
BUTTONS = ("left", "right", "middle")
MODIFIERS = ("Alt", "Control", "Meta", "Shift")

HELPERS = """
  const selector = [
    'a[href]', 'button', 'input:not([type=hidden])', 'textarea', 'select', 'summary',
    '[contenteditable=""]', '[contenteditable=true]', '[onclick]', '[role=button]', '[role=link]',
    '[role=tab]', '[role=menuitem]', '[role=menuitemcheckbox]', '[role=option]', '[role=checkbox]',
    '[role=radio]', '[role=switch]', '[role=combobox]', '[role=textbox]', '[role=treeitem]',
    '[role=gridcell]', '[role=row]',
  ].join(', ');
  const clean = (text, max) => (text || '').replace(/\\s+/g, ' ').trim().slice(0, max);
  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'input') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
      if (type === 'checkbox' || type === 'radio') return type;
      return 'textbox';
    }
    return el.isContentEditable ? 'textbox' : 'clickable';
  };
  const labelledBy = (el) =>
    (el.getAttribute('aria-labelledby') || '')
      .split(/\\s+/)
      .filter(Boolean)
      .map((id) => document.getElementById(id)?.innerText || '')
      .join(' ');
  const besideLabel = (el) => {
    if (!['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return '';
    const cell = el.closest('td');
    const before = cell?.previousElementSibling;
    return before ? before.innerText : '';
  };
  const nameOf = (el) => {
    const buttonInput = el.tagName === 'INPUT' && roleOf(el) === 'button';
    const ownText = el.tagName === 'INPUT' || el.tagName === 'SELECT' ? '' : el.innerText;
    return clean(
      el.getAttribute('aria-label') ||
        labelledBy(el) ||
        (el.labels && el.labels[0] ? el.labels[0].innerText : '') ||
        (buttonInput ? el.value : '') ||
        ownText ||
        el.getAttribute('placeholder') ||
        el.getAttribute('title') ||
        el.getAttribute('alt') ||
        el.querySelector('img[alt]')?.getAttribute('alt') ||
        besideLabel(el) ||
        el.getAttribute('name'),
      nameChars,
    );
  };
  const valueOf = (el) => {
    if (el.tagName === 'SELECT') return clean(el.selectedOptions[0]?.innerText, valueChars);
    if (el.type === 'checkbox' || el.type === 'radio') return el.checked ? 'checked' : 'unchecked';
    if (el.type === 'password') return el.value ? '(hidden)' : '';
    if (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && roleOf(el) === 'textbox')) {
      return clean(el.value, valueChars);
    }
    return '';
  };
  const areaOf = (el) => {
    const box = el.closest('[role=dialog], dialog, .ui-dialog, .modal');
    if (!box) return '';
    const heading = box.querySelector('[role=heading], h1, h2, h3, .ui-dialog-title, .modal-title');
    return clean(box.getAttribute('aria-label') || heading?.innerText, nameChars);
  };
  const pointer = (el) => getComputedStyle(el).cursor === 'pointer';
  const describe = (el) => {
    const box = el.getBoundingClientRect();
    return {
      role: roleOf(el),
      name: nameOf(el),
      value: valueOf(el),
      area: areaOf(el),
      disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
    };
  };
"""

SNAPSHOT_SCRIPT = (
    "({ start, limit, nameChars, valueChars, attribute }) => {"
    + HELPERS
    + """
  const marked = new Set(document.querySelectorAll(selector));
  const clickable = new Set();
  for (const el of document.body ? document.body.querySelectorAll('*') : []) {
    if (marked.has(el) || !pointer(el) || el.closest(selector)) continue;
    if (el.parentElement && pointer(el.parentElement)) continue;
    clickable.add(el);
  }
  const ordered = [...marked, ...clickable].sort((a, b) =>
    a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
  );

  document.querySelectorAll(`[${attribute}]`).forEach((el) => el.removeAttribute(attribute));
  const found = [];
  for (const el of ordered) {
    if (found.length >= limit) break;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    const item = describe(el);
    if (clickable.has(el) && !item.name) continue;
    const ref = start + found.length;
    el.setAttribute(attribute, String(ref));
    found.push({ ref, ...item });
  }
  return found;
}
"""
)

POINT_SCRIPT = (
    "({ x, y, nameChars, valueChars }) => {"
    + HELPERS
    + """
  const hit = document.elementFromPoint(x, y);
  if (!hit || hit === document.body || hit === document.documentElement) return null;
  const control = hit.closest(selector);
  if (control) return describe(control);

  let el = hit;
  while (el.parentElement && pointer(el.parentElement)) el = el.parentElement;
  return pointer(el) ? describe(el) : { ...describe(el), role: 'text' };
}
"""
)

TEXT_SCRIPT = "() => document.body ? document.body.innerText : ''"
SHAPE_SCRIPT = "() => document.body ? document.body.innerText.length + document.querySelectorAll('*').length : -1"

T = TypeVar("T")


class BrowserError(Exception):
    pass


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Element:
    role: str
    name: str
    value: str
    area: str
    disabled: bool
    x: float
    y: float
    width: float
    height: float
    ref: int = 0

    @property
    def center(self) -> Point:
        return Point(round(self.x + self.width / 2), round(self.y + self.height / 2))

    def describe(self) -> str:
        parts = [f'{self.role} "{self.name}"' if self.name else self.role]
        if self.value:
            parts.append(f'= "{self.value}"')
        if self.disabled:
            parts.append("(disabled)")
        if self.area:
            parts.append(f'in "{self.area}"')
        return " ".join(parts)


@dataclass(frozen=True)
class Target:
    ref: int | None = None
    point: Point | None = None
    locator: str | None = None

    def __post_init__(self) -> None:
        given = [self.ref is not None, self.point is not None, bool(self.locator)]
        if given.count(True) != 1:
            raise BrowserError("Aim with exactly one of: ref, x and y, or locator.")


@dataclass(frozen=True)
class Aim:
    point: Point
    label: str


@dataclass(frozen=True)
class View:
    url: str
    title: str
    width: int
    height: int
    elements: list[Element]
    text: str


@dataclass
class _Job:
    work: Callable[[Driver], Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None


def _first_line(exc: Exception) -> str:
    return next(iter(str(exc).splitlines()), type(exc).__name__)


def _inside(box: dict[str, float], point: Point) -> bool:
    return box["x"] <= point.x <= box["x"] + box["width"] and box["y"] <= point.y <= box["y"] + box["height"]


def _viewport(page: Page) -> dict[str, int]:
    size = page.viewport_size
    if size is None:
        raise BrowserError("The browser page has no screen size.")
    return size


def _evaluate(frame: Frame, script: str, arg: Any = None) -> Any:
    try:
        return frame.evaluate(script, arg)
    except PlaywrightError as exc:
        if not any(hint in str(exc) for hint in NAVIGATED):
            raise
    frame.page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
    return frame.evaluate(script, arg)


class Driver:
    def __init__(self, context: BrowserContext, hostname: str) -> None:
        self._context = context
        self._hostname = hostname
        self._frames: dict[int, Frame] = {}
        self._elements: dict[int, Element] = {}

    @property
    def page(self) -> Page:
        live = [p for p in self._context.pages if not p.is_closed()]
        return live[-1] if live else self._context.new_page()

    def add_cookies(self, cookies: dict[str, str]) -> None:
        self._context.add_cookies(
            [{"name": name, "value": value, "domain": self._hostname, "path": "/"} for name, value in cookies.items()]
        )

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        self._settle(PAGE_SETTLE_SECONDS, wait_load=True)

    def snapshot(self) -> View:
        page = self.page
        self._frames, self._elements = {}, {}
        texts: list[str] = []
        for frame in page.frames:
            if frame.is_detached() or frame.url in ("", BLANK_PAGE):
                continue

            room = MAX_ELEMENTS - len(self._elements)
            if room > 0:
                self._collect(frame, room)

            text = _evaluate(frame, TEXT_SCRIPT).strip()
            if text:
                texts.append(text if frame is page.main_frame else f"[frame {frame.name or frame.url}]\n{text}")

        size = _viewport(page)
        return View(
            page.url,
            page.title(),
            size["width"],
            size["height"],
            list(self._elements.values()),
            "\n\n".join(texts)[:TEXT_CHARS],
        )

    def _offset(self, frame: Frame) -> Point:
        if frame.parent_frame is None:
            return Point(0, 0)

        box = frame.frame_element().bounding_box()
        if box is None:
            raise BrowserError("A frame on the page is not visible.")
        return Point(box["x"], box["y"])

    def _collect(self, frame: Frame, room: int) -> None:
        offset = self._offset(frame)
        found = _evaluate(
            frame,
            SNAPSHOT_SCRIPT,
            {
                "start": len(self._elements) + 1,
                "limit": room,
                "nameChars": NAME_CHARS,
                "valueChars": VALUE_CHARS,
                "attribute": REF_ATTRIBUTE,
            },
        )
        for item in found:
            element = Element(**{**item, "x": item["x"] + offset.x, "y": item["y"] + offset.y})
            self._elements[element.ref] = element
            self._frames[element.ref] = frame

    def _ref_locator(self, ref: int) -> Locator:
        if ref not in self._elements:
            raise BrowserError(f"No element [{ref}] in the last snapshot. Take a new snapshot.")

        frame = self._frames[ref]
        if frame.is_detached():
            raise BrowserError(f"Element [{ref}] is gone: its frame closed. Take a new snapshot.")

        found = frame.locator(f'[{REF_ATTRIBUTE}="{ref}"]')
        if found.count() == 0:
            raise BrowserError(f"Element [{ref}] is gone from the page. Take a new snapshot.")
        return found.first

    def _selector_locator(self, selector: str) -> Locator:
        for frame in self.page.frames:
            if frame.is_detached():
                continue
            found = frame.locator(selector)
            if found.count() > 0:
                return found.first

        raise BrowserError(f"Nothing on the page matches {selector}.")

    def aim(self, target: Target) -> Aim:
        if target.point is not None:
            return Aim(target.point, self.describe_at(target.point))

        found = (
            self._ref_locator(target.ref) if target.ref is not None else self._selector_locator(target.locator or "")
        )
        found.scroll_into_view_if_needed()
        box = found.bounding_box()
        if box is None:
            raise BrowserError("That element is not visible.")

        point = Point(round(box["x"] + box["width"] / 2), round(box["y"] + box["height"] / 2))
        return Aim(point, self.describe_at(point))

    def describe_at(self, point: Point) -> str:
        page = self.page
        size = _viewport(page)
        if not (0 <= point.x < size["width"] and 0 <= point.y < size["height"]):
            raise BrowserError(f"({point.x}, {point.y}) is outside the {size['width']}x{size['height']} screen.")

        frame, offset, area = page.main_frame, Point(0, 0), float("inf")
        for child in page.frames:
            if child.parent_frame is None or child.is_detached():
                continue
            box = child.frame_element().bounding_box()
            if box is not None and _inside(box, point) and box["width"] * box["height"] < area:
                frame, offset, area = child, Point(box["x"], box["y"]), box["width"] * box["height"]

        found = _evaluate(
            frame,
            POINT_SCRIPT,
            {"x": point.x - offset.x, "y": point.y - offset.y, "nameChars": NAME_CHARS, "valueChars": VALUE_CHARS},
        )
        if found is None:
            return f"empty space at ({point.x}, {point.y})"
        return f"{Element(**found).describe()} at ({point.x}, {point.y})"

    def move(self, point: Point) -> None:
        self.page.mouse.move(point.x, point.y, steps=MOVE_STEPS)
        self._after(self.page.url)

    def click(self, point: Point, button: str, count: int, modifiers: list[str]) -> None:
        page = self.page
        before = page.url
        page.mouse.move(point.x, point.y, steps=MOVE_STEPS)
        for key in modifiers:
            page.keyboard.down(key)
        page.mouse.click(point.x, point.y, button=button, click_count=count)
        for key in reversed(modifiers):
            page.keyboard.up(key)

        self._after(before)

    def press_mouse(self, point: Point, button: str, down: bool) -> None:
        page = self.page
        before = page.url
        page.mouse.move(point.x, point.y, steps=MOVE_STEPS)
        if down:
            page.mouse.down(button=button)
        else:
            page.mouse.up(button=button)

        self._after(before)

    def drag(self, start: Point, end: Point) -> None:
        page = self.page
        before = page.url
        page.mouse.move(start.x, start.y, steps=MOVE_STEPS)
        page.mouse.down()
        page.mouse.move(end.x, end.y, steps=DRAG_STEPS)
        page.mouse.up()

        self._after(before)

    def scroll(self, point: Point, dx: int, dy: int) -> None:
        page = self.page
        page.mouse.move(point.x, point.y)
        page.mouse.wheel(dx, dy)
        self._after(page.url)

    def type(self, text: str, clear: bool) -> None:
        page = self.page
        before = page.url
        if clear:
            page.keyboard.press(SELECT_ALL_KEY)
            page.keyboard.press(ERASE_KEY)

        page.keyboard.type(text)
        self._after(before)

    def press(self, key: str) -> None:
        page = self.page
        before = page.url
        page.keyboard.press(key)
        self._after(before)

    def select(self, ref: int, option: str) -> None:
        before = self.page.url
        self._ref_locator(ref).select_option(label=option)
        self._after(before)

    def wait_for(self, text: str, selector: str, url_part: str, seconds: float) -> str:
        deadline = time.monotonic() + min(seconds, MAX_WAIT_SECONDS)
        while True:
            page = self.page
            if self._matches(page, text, selector, url_part):
                return page.url
            if time.monotonic() > deadline:
                raise BrowserError(f"Waited {seconds:g}s and the page still does not show it.")
            page.wait_for_timeout(WAIT_POLL_MS)

    def _matches(self, page: Page, text: str, selector: str, url_part: str) -> bool:
        if url_part and url_part not in page.url:
            return False
        frames = [f for f in page.frames if not f.is_detached()]
        if text and not any(text in _evaluate(f, TEXT_SCRIPT) for f in frames):
            return False
        return not selector or any(f.locator(selector).count() > 0 for f in frames)

    def screenshot(self) -> bytes:
        return self.page.screenshot(type="jpeg", quality=SCREENSHOT_QUALITY)

    def where(self) -> tuple[str, str]:
        page = self.page
        return page.title(), page.url

    def resize(self, width: int, height: int) -> None:
        self.page.set_viewport_size({"width": width, "height": height})

    def idle(self) -> None:
        self.page.wait_for_timeout(IDLE_LOOP_MS)

    def _after(self, before: str) -> None:
        self.page.wait_for_timeout(ACTION_PAUSE_MS)
        moved = self.page.url != before
        self._settle(PAGE_SETTLE_SECONDS if moved else ACTION_SETTLE_SECONDS, wait_load=moved)

    def _settle(self, seconds: float, wait_load: bool) -> None:
        page = self.page
        if wait_load:
            page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)

        deadline = time.monotonic() + seconds
        shape = _evaluate(page.main_frame, SHAPE_SCRIPT)
        while time.monotonic() < deadline:
            page.wait_for_timeout(SETTLE_POLL_MS)
            now = _evaluate(page.main_frame, SHAPE_SCRIPT)
            if now == shape and now > 0:
                return
            shape = now


class Pilot:
    def __init__(
        self,
        base_url: str,
        cookies: dict[str, str],
        debug_port: int,
        size: tuple[int, int],
        on_exit: Callable[[Pilot], None],
    ) -> None:
        if not browser_is_installed():
            raise BrowserError(NOT_INSTALLED)

        parts = urlsplit(base_url)
        if not parts.hostname:
            raise BrowserError(f"Not an instance URL: {base_url!r}")

        self.base_url = base_url.rstrip("/")
        self._host = parts.netloc.lower()
        self._hostname = parts.hostname
        self._cookies = cookies
        self._port = debug_port
        self._size = {"width": size[0], "height": size[1]}
        self._on_exit = on_exit
        self._jobs: queue.SimpleQueue[_Job | None] = queue.SimpleQueue()
        self._started = threading.Event()
        self._failure: str | None = None
        self._blocked: list[str] = []
        self._thread = threading.Thread(target=self._run, name="agent-browser", daemon=True)
        self._thread.start()

        if not self._started.wait(START_TIMEOUT_SECONDS):
            self.close()
            raise BrowserError("The browser did not start in time.")
        if self._failure is not None:
            raise BrowserError(self._failure)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def failure(self) -> str | None:
        return self._failure

    def close(self) -> None:
        self._jobs.put(None)

    def call(self, work: Callable[[Driver], T]) -> T:
        if not self.alive:
            raise BrowserError(self._failure or CLOSED)

        job = _Job(work)
        self._jobs.put(job)
        deadline = time.monotonic() + CALL_TIMEOUT_SECONDS
        while not job.done.wait(CALL_POLL_SECONDS):
            if not self.alive:
                raise BrowserError(self._failure or CLOSED)
            if time.monotonic() > deadline:
                raise BrowserError("The browser did not respond in time.")

        if job.error is not None:
            raise job.error
        return job.result

    def take_blocked(self) -> list[str]:
        blocked, self._blocked = self._blocked, []
        return blocked

    def url_of(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def on_host(self, url: str) -> bool:
        return urlsplit(url).netloc.lower() == self._host

    def goto(self, url: str) -> None:
        if not self.on_host(url):
            raise BrowserError(f"This browser only opens {self._host}, not {url}.")
        self.call(lambda d: d.goto(url))

    def add_cookies(self, cookies: dict[str, str]) -> None:
        self.call(lambda d: d.add_cookies(cookies))

    def snapshot(self) -> View:
        return self.call(lambda d: d.snapshot())

    def where(self) -> tuple[str, str]:
        return self.call(lambda d: d.where())

    def aim(self, target: Target) -> Aim:
        return self.call(lambda d: d.aim(target))

    def move(self, point: Point) -> None:
        self.call(lambda d: d.move(point))

    def click(self, point: Point, button: str, count: int, modifiers: list[str]) -> None:
        self.call(lambda d: d.click(point, button, count, modifiers))

    def press_mouse(self, point: Point, button: str, down: bool) -> None:
        self.call(lambda d: d.press_mouse(point, button, down))

    def drag(self, start: Point, end: Point) -> None:
        self.call(lambda d: d.drag(start, end))

    def scroll(self, point: Point, dx: int, dy: int) -> None:
        self.call(lambda d: d.scroll(point, dx, dy))

    def type(self, text: str, clear: bool) -> None:
        self.call(lambda d: d.type(text, clear))

    def press(self, key: str) -> None:
        self.call(lambda d: d.press(key))

    def select(self, ref: int, option: str) -> None:
        self.call(lambda d: d.select(ref, option))

    def wait_for(self, text: str, selector: str, url_part: str, seconds: float) -> str:
        return self.call(lambda d: d.wait_for(text, selector, url_part, seconds))

    def screenshot(self) -> bytes:
        return self.call(lambda d: d.screenshot())

    def resize(self, width: int, height: int) -> None:
        self.call(lambda d: d.resize(width, height))

    def _run(self) -> None:
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile, sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    profile,
                    headless=True,
                    channel=SCREEN_CHANNEL,
                    args=[*LAUNCH_ARGS, f"--remote-debugging-port={self._port}"],
                    viewport=self._size,
                    user_agent=desktop_user_agent(),
                )

                context.set_default_timeout(ACTION_TIMEOUT_MS)
                context.route(EVERY_REQUEST, self._fence)
                driver = Driver(context, self._hostname)
                if self._cookies:
                    driver.add_cookies(self._cookies)
                self._started.set()
                self._serve(driver)
                context.close()
        except PlaywrightError as exc:
            self._failure = f"The browser stopped: {_first_line(exc)}"
        finally:
            self._started.set()
            self._fail_waiting()
            self._on_exit(self)

    def _serve(self, driver: Driver) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                driver.idle()
                continue
            if job is None:
                return
            self._do(job, driver)

    def _do(self, job: _Job, driver: Driver) -> None:
        try:
            job.result = job.work(driver)
        except BrowserError as exc:
            job.error = exc
        except PlaywrightTimeout:
            job.error = BrowserError("The page did not respond in time.")
        except PlaywrightError as exc:
            job.error = BrowserError(_first_line(exc))
        finally:
            job.done.set()

    def _fail_waiting(self) -> None:
        while not self._jobs.empty():
            job = self._jobs.get_nowait()
            if job is not None:
                job.error = BrowserError(self._failure or CLOSED)
                job.done.set()

    def _fence(self, route: Route) -> None:
        request = route.request
        main = request.is_navigation_request() and request.frame.parent_frame is None
        if main and not self.on_host(request.url):
            self._blocked.append(request.url)
            route.fulfill(status=STAY_PUT_STATUS)
            return

        route.continue_()
