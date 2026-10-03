from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from filelock import FileLock

from .errors import OvError
from .paths import config_file, home, write_atomic

SESSIONS_KEY = "sessions"
CURRENT_KEY = "current"

LEGACY_SESSION_KEY = "session"
LEGACY_BASE_URL_KEY = "base_url"

LOCK_TIMEOUT_SECONDS = 30

_locks: dict[str, FileLock] = {}


# One object per path: FileLock re-enters only through the same instance.
def lock() -> FileLock:
    path = str(home() / "config.lock")
    if path not in _locks:
        _locks[path] = FileLock(path, timeout=LOCK_TIMEOUT_SECONDS)
    return _locks[path]


def read() -> dict[str, Any]:
    try:
        return _load()
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def _load() -> dict[str, Any]:
    path = config_file()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return _migrated(data)


# Applied on read so an old single-session file keeps working without a write.
def _migrated(data: dict[str, Any]) -> dict[str, Any]:
    legacy = data.get(LEGACY_SESSION_KEY)
    if not isinstance(legacy, dict) or SESSIONS_KEY in data:
        data.pop(LEGACY_BASE_URL_KEY, None)
        return data

    from .session import default_alias

    base_url = (legacy.get("base_url") or data.get(LEGACY_BASE_URL_KEY) or "").rstrip("/")
    data.pop(LEGACY_SESSION_KEY, None)
    data.pop(LEGACY_BASE_URL_KEY, None)
    if not base_url:
        return data

    alias = legacy.get("alias") or default_alias(base_url)
    legacy["base_url"] = base_url
    legacy["alias"] = alias
    data[SESSIONS_KEY] = {alias: legacy}
    data[CURRENT_KEY] = alias
    return data


def mutate(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with lock():
        # A transient read failure (an antivirus lock on Windows) must not erase every session.
        try:
            data = _load()
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            raise OvError(f"Cannot read {config_file()}: {exc}") from exc
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
