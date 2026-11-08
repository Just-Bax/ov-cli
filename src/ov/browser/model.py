from __future__ import annotations

from dataclasses import dataclass

BUTTONS = ("left", "right", "middle")
MODIFIERS = ("Alt", "Control", "Meta", "Shift")
TIMED_OUT = "Timed out: {reason}. Take a new snapshot before trying something else."
PROGRESS_STEPS = ("waiting", "retrying", "attempting", "scrolling", "element is", "locator resolved", "Call log")


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


def first_line(exc: Exception) -> str:
    return next(iter(str(exc).splitlines()), type(exc).__name__)


def timeout_reason(exc: Exception) -> str:
    lines = [line.strip(" -") for line in str(exc).splitlines()[1:]]
    causes = [line for line in lines if line and not any(step in line for step in PROGRESS_STEPS)]
    return TIMED_OUT.format(reason=causes[-1] if causes else first_line(exc))
