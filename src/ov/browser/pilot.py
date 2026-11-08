from __future__ import annotations

import queue
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, TypeVar
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from ov.browser.dialogs import Dialogs
from ov.browser.driver import Driver
from ov.browser.model import (
    Aim,
    BrowserError,
    Dialog,
    DialogOpen,
    Point,
    Tab,
    Target,
    View,
    first_line,
    timeout_reason,
)
from ov.browser.pages import CLOSED
from ov.browser.scripts import PICKER_SCRIPT
from ov.onevizion.login import SCREEN_CHANNEL, browser_is_installed, desktop_user_agent

LAUNCH_ARGS = ["--no-first-run", "--no-default-browser-check"]
ACTION_TIMEOUT_MS = 15_000
START_TIMEOUT_SECONDS = 90
CALL_TIMEOUT_SECONDS = 120
CALL_POLL_SECONDS = 0.5
NOT_INSTALLED = "The browser is not installed. Run: ov setup"

T = TypeVar("T")


class Owner(Protocol):
    def changed(self, change: dict[str, Any]) -> None: ...
    def exited(self, pilot: Pilot) -> None: ...


@dataclass
class _Job:
    work: Callable[[Driver], Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None


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
        self._dialogs = Dialogs(owner.changed)
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

    def preview(self, name: str, page: str) -> str:
        return self.url_of(self.call(lambda d: d.preview(name, page)))

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

    def upload(self, target: Target, point: Point, paths: list[str]) -> None:
        self.call(lambda d: d.upload(target, point, paths))

    def pause(self, seconds: float) -> None:
        self.call(lambda d: d.pause(seconds))

    def wait_for(self, text: str, selector: str, url_part: str, seconds: float) -> None:
        self.call(lambda d: d.wait_for(text, selector, url_part, seconds))

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
            self._failure = f"The browser stopped: {first_line(exc)}"
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
            job.error = BrowserError(timeout_reason(exc))
        except PlaywrightError as exc:
            job.error = BrowserError(first_line(exc))
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
