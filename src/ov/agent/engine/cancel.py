from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class Cancelled(Exception):
    pass


class Cancel:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._hooks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def is_set(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled

    def wait(self, seconds: float) -> bool:
        return self._event.wait(seconds)

    def set(self) -> None:
        with self._lock:
            self._event.set()
            hooks = list(self._hooks)
        for hook in hooks:
            hook()

    @contextmanager
    def hook(self, fn: Callable[[], None]) -> Iterator[None]:
        with self._lock:
            fire = self._event.is_set()
            self._hooks.append(fn)
        try:
            if fire:
                fn()
            yield
        finally:
            with self._lock:
                self._hooks.remove(fn)
