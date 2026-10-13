from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ov.core.paths import cache_dir, write_atomic

CACHE_KEY_CHARS = 16


class Cache:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds

    def _path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:CACHE_KEY_CHARS]
        return cache_dir() / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if self.ttl_seconds <= 0 or not path.exists():
            return None

        record = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - record["saved_at"] > self.ttl_seconds:
            return None
        return record["value"]

    def set(self, key: str, value: Any) -> None:
        record = {"key": key, "saved_at": time.time(), "value": value}
        write_atomic(self._path(key), json.dumps(record))

    def clear(self) -> int:
        entries = list(cache_dir().glob("*.json"))
        for path in entries:
            path.unlink()
        return len(entries)
