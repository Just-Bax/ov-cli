from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .paths import cache_dir


class Cache:
    """TTL cache for API responses.

    A ttl of 0 disables reads but still writes, so --refresh replaces stale
    entries rather than leaving them.
    """

    def __init__(self, root: Path | None = None, ttl_seconds: int = 600) -> None:
        self._root = root
        self.ttl_seconds = ttl_seconds

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else cache_dir()

    def _path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self.root / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        if self.ttl_seconds <= 0:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - record.get("saved_at", 0) > self.ttl_seconds:
            return None
        return record.get("value")

    def set(self, key: str, value: Any) -> None:
        record = {"key": key, "saved_at": time.time(), "value": value}
        try:
            self._path(key).write_text(json.dumps(record), encoding="utf-8")
        except OSError:
            pass

    def clear(self) -> int:
        removed = 0
        for path in self.root.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed
