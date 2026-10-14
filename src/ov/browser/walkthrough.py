from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ov.browser.engine import BrowserError, ElementRef

MAX_STEPS = 60
MAX_ACTIONS_PER_STEP = 6
ACTIONS = ("goto", "click", "fill", "select", "press", "wait", "assert", "pass", "fail")
NEEDS_TARGET = ("click", "fill", "select")
NEEDS_TEXT = ("fill", "select", "wait", "assert")
ACTION_CHARS = 2_000

DESTRUCTIVE = re.compile(
    r"\b(delete|remove|drop|purge|truncate|deactivate|disable|wipe|erase|mass|bulk|run all|run against all)\b",
    re.IGNORECASE,
)


class Status:
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class Action:
    kind: str
    index: int | None = None
    text: str = ""
    reason: str = ""


@dataclass
class StepResult:
    index: int
    text: str
    status: str = Status.PENDING
    detail: str = ""
    action: str = ""
    screenshot: str = ""


class Driver(Protocol):
    def act(self, context: dict[str, Any]) -> Action: ...


class Guard(Protocol):
    def allow(self, goal: str, action: Action, element: str) -> tuple[bool, str]: ...


class Browser(Protocol):
    def goto(self, url: str) -> None: ...
    def click(self, target: ElementRef) -> None: ...
    def fill(self, target: ElementRef, text: str) -> None: ...
    def select(self, target: ElementRef, value: str) -> None: ...
    def press(self, key: str) -> None: ...
    def wait_for_text(self, text: str) -> None: ...
    def url(self) -> str: ...
    def text(self) -> str: ...
    def snapshot(self) -> list[ElementRef]: ...
    def screenshot(self, path: Path) -> None: ...


def parse_action(raw: str) -> Action:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise BrowserError(f"The model did not return a JSON action: {raw[:ACTION_CHARS]}") from None
    if not isinstance(data, dict) or data.get("action") not in ACTIONS:
        raise BrowserError(f"The model returned an unknown action: {raw[:ACTION_CHARS]}")

    kind = data["action"]
    index = data.get("index")
    if kind in NEEDS_TARGET and not isinstance(index, int):
        raise BrowserError(f"The {kind} action needs an element index.")
    text = str(data.get("text") or "")
    if kind in NEEDS_TEXT and not text:
        raise BrowserError(f"The {kind} action needs text.")
    return Action(
        kind=kind, index=index if isinstance(index, int) else None, text=text, reason=str(data.get("reason") or "")
    )


def hard_blocked(goal: str, action: Action, element: str) -> str | None:
    if action.kind not in ("click", "fill", "select"):
        return None
    target = f"{element} {action.text}"
    if DESTRUCTIVE.search(target) and not DESTRUCTIVE.search(goal):
        return f'"{element.strip() or action.text}" looks destructive and the walkthrough did not ask for it.'
    return None


class Walkthrough:
    def __init__(self, browser: Browser, driver: Driver, guard: Guard, shots: Path, cancel: Callable[[], bool]) -> None:
        self._browser = browser
        self._driver = driver
        self._guard = guard
        self._shots = shots
        self._cancel = cancel

    def run(self, goal: str, steps: list[str], on_step: Callable[[StepResult], None]) -> list[StepResult]:
        results = [StepResult(index=i, text=text) for i, text in enumerate(steps[:MAX_STEPS])]
        for result in results:
            if self._cancel():
                result.status = Status.STOPPED
                on_step(result)
                break
            result.status = Status.RUNNING
            on_step(result)
            self._run_step(goal, steps, result)
            on_step(result)
            if result.status in (Status.FAILED, Status.BLOCKED, Status.ERROR):
                break
        return results

    def _run_step(self, goal: str, steps: list[str], result: StepResult) -> None:
        try:
            self._drive_step(goal, steps, result)
        except BrowserError as exc:
            result.status = Status.ERROR
            result.detail = str(exc)
        self._capture(result)

    def _drive_step(self, goal: str, steps: list[str], result: StepResult) -> None:
        for _ in range(MAX_ACTIONS_PER_STEP):
            snapshot = self._browser.snapshot()
            action = self._driver.act(
                {
                    "goal": goal,
                    "steps": steps,
                    "step": result.text,
                    "url": self._browser.url(),
                    "snapshot": [{"index": e.index, "role": e.role, "name": e.name} for e in snapshot],
                    "text": self._browser.text(),
                }
            )
            result.action = f"{action.kind} {action.reason}".strip()
            if self._settle(action, result):
                return
            element = _name_of(snapshot, action.index)
            blocked = hard_blocked(goal, action, element)
            if blocked is None:
                allowed, why = self._guard.allow(goal, action, element)
                blocked = None if allowed else why
            if blocked is not None:
                result.status = Status.BLOCKED
                result.detail = blocked
                return
            self._perform(action, snapshot)
        result.status = Status.FAILED
        result.detail = "The step did not finish in time."

    def _settle(self, action: Action, result: StepResult) -> bool:
        if action.kind == "pass":
            result.status = Status.PASSED
            result.detail = action.reason
            return True
        if action.kind == "fail":
            result.status = Status.FAILED
            result.detail = action.reason or "The step did not match what was expected."
            return True
        if action.kind == "assert":
            present = action.text.lower() in self._browser.text().lower()
            result.status = Status.PASSED if present else Status.FAILED
            result.detail = f'"{action.text}" {"found" if present else "not found"} on the page.'
            return True
        return False

    def _perform(self, action: Action, snapshot: list[ElementRef]) -> None:
        if action.kind == "goto":
            self._browser.goto(action.text or action.reason)
        elif action.kind == "press":
            self._browser.press(action.text)
        elif action.kind == "wait":
            self._browser.wait_for_text(action.text)
        else:
            target = _ref(snapshot, action.index)
            if action.kind == "click":
                self._browser.click(target)
            elif action.kind == "fill":
                self._browser.fill(target, action.text)
            else:
                self._browser.select(target, action.text)

    def _capture(self, result: StepResult) -> None:
        name = f"step-{result.index + 1}.png"
        try:
            self._browser.screenshot(self._shots / name)
            result.screenshot = name
        except BrowserError:
            result.screenshot = ""


def _ref(snapshot: list[ElementRef], index: int | None) -> ElementRef:
    found = next((e for e in snapshot if e.index == index), None)
    if found is None:
        raise BrowserError(f"No element {index} on the page.")
    return found


def _name_of(snapshot: list[ElementRef], index: int | None) -> str:
    found = next((e for e in snapshot if e.index == index), None)
    return found.name if found else ""
