from __future__ import annotations

import queue
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, TypeVar
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, CDPSession, Frame, Locator, Page, sync_playwright
from playwright.sync_api import Dialog as PageDialog
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ov.browser.scripts import ELEMENT_SCRIPT, PICKER_SCRIPT, POINT_SCRIPT, READY_SCRIPT, TEXT_SCRIPT
from ov.onevizion.login import SCREEN_CHANNEL, browser_is_installed, desktop_user_agent

LAUNCH_ARGS = ["--no-first-run", "--no-default-browser-check"]
ACTION_TIMEOUT_MS = 15_000
CLICK_TIMEOUT_MS = 5_000
SNAPSHOT_TIMEOUT_MS = 10_000
NAV_TIMEOUT_MS = 45_000
ACTION_PAUSE_MS = 150
WAIT_POLL_MS = 250
MAX_WAIT_SECONDS = 30
MS_PER_SECOND = 1000
IDLE_LOOP_MS = 40
MOVE_STEPS = 8
DRAG_STEPS = 16
SELECT_ALL_KEY = "ControlOrMeta+A"
ERASE_KEY = "Backspace"
START_TIMEOUT_SECONDS = 90
CALL_TIMEOUT_SECONDS = 120
CALL_POLL_SECONDS = 0.5
NAME_CHARS = 80
VALUE_CHARS = 80
TREE_CHARS = 12_000
SCREENSHOT_QUALITY = 70
SNAPSHOT_MODE = "ai"
LOADED = "complete"
REF_PATTERN = re.compile(r"\[ref=(\w+)\]")
STAY_PUT_STATUS = 204
PAGE_REQUESTS = [{"urlPattern": "*", "resourceType": "Document", "requestStage": "Request"}]
PROMPT = "prompt"
NOT_INSTALLED = "The browser is not installed. Run: ov setup"
CLOSED = "The browser has closed."
NO_DIALOG = "No dialog is open on the page."
ONLY_TAB = "This is the only tab; close the browser instead."
UNKNOWN_REF = "There is no {ref} in the last snapshot. Take a new snapshot and use its refs."
GONE_REF = "{ref} is no longer on the page. Take a new snapshot."
NO_BOX = "{target} is not visible on the page. Scroll to it or take a new snapshot."
NOT_SELECT = "That is not a standard dropdown: click it open and click the option instead."
TREE_CUT = "[{chars} more chars cut. Scroll, or wait or aim with a locator for what you need.]"
TIMED_OUT = "Timed out: {reason}. Take a new snapshot before trying something else."
PROGRESS_STEPS = ("waiting", "retrying", "attempting", "scrolling", "element is", "locator resolved", "Call log")
SLOW_PAGE = "{url} did not load within {seconds}s; the site is slow right now. It may still finish: look again shortly."
NAVIGATED = ("Execution context was destroyed", "Cannot find context", "Frame was detached")
NOT_SELECT_HINT = "not a <select>"
BUTTONS = ("left", "right", "middle")
MODIFIERS = ("Alt", "Control", "Meta", "Shift")

T = TypeVar("T")
Notify = Callable[[dict[str, Any]], None]
Allows = Callable[[str], bool]
Frames = tuple[Page, tuple[str, ...]]


class Owner(Protocol):
    def changed(self, change: dict[str, Any]) -> None: ...
    def exited(self, pilot: Pilot) -> None: ...


class BrowserError(Exception):
    pass


@dataclass(frozen=True)
class Dialog:
    kind: str
    message: str
    default: str


class DialogOpen(BrowserError):
    def __init__(self, dialog: Dialog) -> None:
        super().__init__(f'The page is showing a {dialog.kind}: "{dialog.message}"')
        self.dialog = dialog


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
    ref: str | None = None
    point: Point | None = None
    locator: str | None = None

    def __post_init__(self) -> None:
        given = [bool(self.ref), self.point is not None, bool(self.locator)]
        if given.count(True) != 1:
            raise BrowserError("Aim with exactly one of: ref, x and y, or locator.")


@dataclass(frozen=True)
class Aim:
    point: Point
    label: str
    role: str


@dataclass(frozen=True)
class Tab:
    index: int
    title: str
    url: str
    active: bool


@dataclass(frozen=True)
class View:
    url: str
    title: str
    width: int
    height: int
    loading: bool
    tabs: list[Tab]
    tree: str


@dataclass
class _Job:
    work: Callable[[Driver], Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None


@dataclass(frozen=True)
class _Answer:
    accept: bool
    text: str


def _first_line(exc: Exception) -> str:
    return next(iter(str(exc).splitlines()), type(exc).__name__)


def _timeout_reason(exc: Exception) -> str:
    lines = [line.strip(" -") for line in str(exc).splitlines()[1:]]
    causes = [line for line in lines if line and not any(step in line for step in PROGRESS_STEPS)]
    return TIMED_OUT.format(reason=causes[-1] if causes else _first_line(exc))


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


class _Dialogs:
    def __init__(self, notify: Notify) -> None:
        self.open: Dialog | None = None
        self._notify = notify
        self._answers: queue.SimpleQueue[_Answer] = queue.SimpleQueue()

    def hold(self, dialog: PageDialog) -> None:
        self.open = Dialog(dialog.type, dialog.message, dialog.default_value)
        self._notify({"dialog": asdict(self.open)})

        answer = self._answers.get()
        if not answer.accept:
            dialog.dismiss()
        elif dialog.type == PROMPT:
            dialog.accept(answer.text)
        else:
            dialog.accept()

    def answer(self, accept: bool, text: str) -> None:
        if self.open is None:
            raise BrowserError(NO_DIALOG)
        self.open = None
        self._notify({"dialog": None})
        self._answers.put(_Answer(accept, text))


class Driver:
    def __init__(
        self, context: BrowserContext, hostname: str, size: dict[str, int], dialogs: _Dialogs, allows: Allows
    ) -> None:
        self._context = context
        self._hostname = hostname
        self._size = dict(size)
        self._dialogs = dialogs
        self._allows = allows
        self._refs: set[str] = set()
        self._tabs: list[Page] = []
        self._active: Page | None = None
        self._targets: dict[Page, str] = {}
        self.changed = True

        self._fence()
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

    def _fence(self) -> None:
        browser = self._context.browser
        if browser is None:
            raise BrowserError("The browser has no control session to keep pages on the instance.")

        session = browser.new_browser_cdp_session()
        session.on("Fetch.requestPaused", lambda event: self._paused(session, event))
        session.send("Fetch.enable", {"patterns": PAGE_REQUESTS})

    def _paused(self, session: CDPSession, event: dict[str, Any]) -> None:
        request = event["requestId"]
        if self._allows(event["request"]["url"]):
            session.send("Fetch.continueRequest", {"requestId": request})
        else:
            session.send("Fetch.fulfillRequest", {"requestId": request, "responseCode": STAY_PUT_STATUS})

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

    def add_cookies(self, cookies: dict[str, str]) -> None:
        self._context.add_cookies(
            [{"name": name, "value": value, "domain": self._hostname, "path": "/"} for name, value in cookies.items()]
        )

    def goto(self, url: str) -> None:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except PlaywrightTimeout:
            raise BrowserError(SLOW_PAGE.format(url=url, seconds=NAV_TIMEOUT_MS // MS_PER_SECOND)) from None
        self._refs = set()

    def snapshot(self) -> View:
        page = self.page
        url = page.url
        tree = self._tree(page)
        if page.url != url:
            page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
            tree = self._tree(page)

        self._refs = set(REF_PATTERN.findall(tree))
        size = _viewport(page)
        loading = _evaluate(page.main_frame, READY_SCRIPT) != LOADED

        extra = len(tree) - TREE_CHARS
        if extra > 0:
            tree = f"{tree[:TREE_CHARS]}\n{TREE_CUT.format(chars=extra)}"
        return View(page.url, page.title(), size["width"], size["height"], loading, self.tabs(), tree)

    def _tree(self, page: Page) -> str:
        try:
            return page.aria_snapshot(mode=SNAPSHOT_MODE, timeout=SNAPSHOT_TIMEOUT_MS)
        except PlaywrightError as exc:
            if not any(hint in str(exc) for hint in NAVIGATED):
                raise

        page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
        return page.aria_snapshot(mode=SNAPSHOT_MODE, timeout=SNAPSHOT_TIMEOUT_MS)

    def _frames(self) -> Frames:
        page = self.page
        return page, tuple(f.url for f in page.frames if not f.is_detached())

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
            return Aim(point, f"empty space at ({point.x}, {point.y})", "")

        element = Element(**found)
        return Aim(point, f"{element.describe()} at ({point.x}, {point.y})", element.role)

    def center(self) -> Point:
        size = _viewport(self.page)
        return Point(size["width"] // 2, size["height"] // 2)

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

    def pause(self, seconds: float) -> None:
        self.page.wait_for_timeout(min(seconds, MAX_WAIT_SECONDS) * MS_PER_SECOND)

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
        size = {"width": width, "height": height}
        if size == self._size:
            return

        self._size = size
        for page in self._tabs:
            if not page.is_closed():
                page.set_viewport_size(self._size)

    def idle(self) -> None:
        self.page.wait_for_timeout(IDLE_LOOP_MS)

    def after_dialog(self) -> None:
        self._after(self._frames())

    def _after(self, before: Frames) -> None:
        page, urls = before
        page.wait_for_timeout(ACTION_PAUSE_MS)
        if page.is_closed():
            return

        for frame in page.frames:
            if not frame.is_detached() and frame.url not in urls:
                frame.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)


class Pilot:
    def __init__(
        self,
        base_url: str,
        cookies: dict[str, str],
        debug_port: int,
        size: tuple[int, int],
        owner: Owner,
    ) -> None:
        if not browser_is_installed():
            raise BrowserError(NOT_INSTALLED)

        parts = urlsplit(base_url)
        if not parts.hostname:
            raise BrowserError(f"Not an instance URL: {base_url!r}")

        self.base_url = base_url.rstrip("/")
        self.active_target: str | None = None
        self._host = parts.netloc.lower()
        self._hostname = parts.hostname
        self._cookies = cookies
        self._port = debug_port
        self._size = {"width": size[0], "height": size[1]}
        self._owner = owner
        self._dialogs = _Dialogs(owner.changed)
        self._jobs: queue.SimpleQueue[_Job | None] = queue.SimpleQueue()
        self._running: _Job | None = None
        self._started = threading.Event()
        self._failure: str | None = None
        self._blocked: list[str] = []
        self._thread = threading.Thread(target=self._run, name="agent-browser", daemon=True)
        self._start()

    def _start(self) -> None:
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

    @property
    def dialog(self) -> Dialog | None:
        return self._dialogs.open

    def close(self) -> None:
        if self._dialogs.open is not None:
            self._dialogs.answer(False, "")
        self._jobs.put(None)

    def call(self, work: Callable[[Driver], T]) -> T:
        self._check()
        job = _Job(work)
        self._jobs.put(job)
        return self._finish(job)

    def answer(self, accept: bool, text: str) -> None:
        held = self._running
        self._dialogs.answer(accept, text)
        if held is not None:
            self._finish(held)
        self.call(lambda d: d.after_dialog())

    def _check(self) -> None:
        if not self.alive:
            raise BrowserError(self._failure or CLOSED)
        if self._dialogs.open is not None:
            raise DialogOpen(self._dialogs.open)

    def _finish(self, job: _Job) -> Any:
        deadline = time.monotonic() + CALL_TIMEOUT_SECONDS
        while not job.done.wait(CALL_POLL_SECONDS):
            self._check()
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

    def tabs(self) -> list[Tab]:
        return self.call(lambda d: d.tabs())

    def aim(self, target: Target) -> Aim:
        return self.call(lambda d: d.aim(target))

    def center(self) -> Point:
        return self.call(lambda d: d.center())

    def move(self, target: Target, point: Point) -> None:
        self.call(lambda d: d.move(target, point))

    def click(self, target: Target, point: Point, button: str, count: int, modifiers: list[str]) -> None:
        self.call(lambda d: d.click(target, point, button, count, modifiers))

    def press_mouse(self, point: Point, button: str, down: bool) -> None:
        self.call(lambda d: d.press_mouse(point, button, down))

    def drag(self, start: Point, end: Point) -> None:
        self.call(lambda d: d.drag(start, end))

    def scroll(self, point: Point, dx: int, dy: int) -> None:
        self.call(lambda d: d.scroll(point, dx, dy))

    def type(self, target: Target | None, point: Point | None, text: str, clear: bool) -> None:
        self.call(lambda d: d.type(target, point, text, clear))

    def press(self, key: str) -> None:
        self.call(lambda d: d.press(key))

    def select(self, target: Target, option: str) -> None:
        self.call(lambda d: d.select(target, option))

    def pause(self, seconds: float) -> None:
        self.call(lambda d: d.pause(seconds))

    def wait_for(self, text: str, selector: str, url_part: str, seconds: float) -> str:
        return self.call(lambda d: d.wait_for(text, selector, url_part, seconds))

    def screenshot(self) -> bytes:
        return self.call(lambda d: d.screenshot())

    def resize(self, width: int, height: int) -> None:
        self.call(lambda d: d.resize(width, height))

    def switch(self, index: int) -> None:
        self.call(lambda d: d.switch(index))

    def close_tab(self, index: int) -> None:
        self.call(lambda d: d.close_tab(index))

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
                context.add_init_script(PICKER_SCRIPT)
                driver = Driver(context, self._hostname, self._size, self._dialogs, self._allows)
                if self._cookies:
                    driver.add_cookies(self._cookies)

                self._publish(driver)
                self._started.set()
                self._serve(driver)
                context.close()
        except PlaywrightError as exc:
            self._failure = f"The browser stopped: {_first_line(exc)}"
        finally:
            self._started.set()
            self._fail_waiting()
            self._owner.exited(self)

    def _serve(self, driver: Driver) -> None:
        while True:
            if driver.changed:
                self._publish(driver)

            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                driver.idle()
                continue

            if job is None:
                return

            self._do(job, driver)

    def _publish(self, driver: Driver) -> None:
        driver.changed = False
        self.active_target = driver.active_target()
        self._owner.changed({"tabs": [asdict(tab) for tab in driver.tabs()]})

    def _do(self, job: _Job, driver: Driver) -> None:
        self._running = job
        try:
            job.result = job.work(driver)
        except BrowserError as exc:
            job.error = exc
        except PlaywrightTimeout as exc:
            job.error = BrowserError(_timeout_reason(exc))
        except PlaywrightError as exc:
            job.error = BrowserError(_first_line(exc))
        finally:
            self._running = None
            job.done.set()

    def _fail_waiting(self) -> None:
        while not self._jobs.empty():
            job = self._jobs.get_nowait()
            if job is not None:
                job.error = BrowserError(self._failure or CLOSED)
                job.done.set()

    def _allows(self, url: str) -> bool:
        if self.on_host(url):
            return True
        self._blocked.append(url)
        return False
