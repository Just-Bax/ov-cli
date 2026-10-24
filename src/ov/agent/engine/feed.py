from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any


class StatusFeed:
    def __init__(self) -> None:
        self._listeners: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> tuple[queue.Queue[dict[str, Any]], Callable[[], None]]:
        channel: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            self._listeners.append(channel)

        def unsubscribe() -> None:
            with self._lock:
                if channel in self._listeners:
                    self._listeners.remove(channel)

        return channel, unsubscribe

    def publish(self, change: dict[str, Any]) -> None:
        with self._lock:
            for channel in self._listeners:
                channel.put(change)


status_feed = StatusFeed()
