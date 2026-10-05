from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from filelock import FileLock

from .errors import OvError
from .paths import config_file, home, write_atomic

SESSIONS_KEY = "sessions"
CURRENT_KEY = "current"

LOCK_TIMEOUT_SECONDS = 30

_locks: dict[str, FileLock] = {}


def lock() -> FileLock:
    path = str(home() / "config.lock")
    if path not in _locks:
        _locks[path] = FileLock(path, timeout=LOCK_TIMEOUT_SECONDS)
    return _locks[path]


def read() -> dict[str, Any]:
    path = config_file()
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise OvError(f"Cannot read {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise OvError(f"{path} is not a JSON object")
    return data


def mutate(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with lock():
        data = read()
        change(data)
        write_atomic(config_file(), json.dumps(data, indent=2))
    return data


def update(**changes: Any) -> dict[str, Any]:
    def apply(data: dict[str, Any]) -> None:
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value

    return mutate(apply)
