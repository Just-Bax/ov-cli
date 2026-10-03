from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any

from . import store
from .paths import credentials_file, write_atomic

SERVICE = "ov-cli"
BACKEND_ENV = "OV_CREDENTIALS"

# Windows Credential Manager caps a blob at 2560 bytes, stored as UTF-16.
CHUNK_CHARS = 1000

_warned = False


# Every access holds the config lock: parallel ov processes refresh tokens, and a reader
# must never see one writer's chunks mixed with another's.
def get(key: str) -> dict[str, Any] | None:
    with store.lock():
        backend = _keyring()
        if backend is not None:
            try:
                found = _decoded(_read_chunks(backend, key) or "")
            except Exception:
                found = None
            if found is not None:
                return found
        return _file_entries().get(key)


def put(key: str, secrets: dict[str, Any]) -> None:
    with store.lock():
        backend = _keyring()
        if backend is not None:
            try:
                _write_chunks(backend, key, json.dumps(secrets, separators=(",", ":")))
            except Exception:
                _forget_keyring(backend, key)
            else:
                _file_change(lambda entries: entries.pop(key, None))
                return

        def store_entry(entries: dict[str, Any]) -> None:
            entries[key] = secrets

        _warn_once()
        _file_change(store_entry)


def delete(key: str) -> None:
    with store.lock():
        backend = _keyring()
        if backend is not None:
            _forget_keyring(backend, key)
        _file_change(lambda entries: entries.pop(key, None))


def _forget_keyring(backend: Any, key: str) -> None:
    try:
        _forget_chunks(backend, key, 0, _count(backend, key))
    except Exception:
        pass
    _forget(backend, key)


def _keyring() -> Any:
    if os.environ.get(BACKEND_ENV, "").strip().lower() == "file":
        return None
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or backend.priority < 1:
            return None
    except Exception:
        return None
    return backend


def _count(backend: Any, key: str) -> int:
    count = backend.get_password(SERVICE, key)
    return int(count) if count and count.isdigit() else 0


def _read_chunks(backend: Any, key: str) -> str | None:
    count = _count(backend, key)
    if not count:
        return None

    parts = [backend.get_password(SERVICE, f"{key}#{index}") for index in range(count)]
    if any(part is None for part in parts):
        return None
    return "".join(parts)


# Chunks first and the count last, so a concurrent reader never sees a half-written entry.
def _write_chunks(backend: Any, key: str, text: str) -> None:
    previous = _count(backend, key)
    parts = [text[i : i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)] or [""]
    for index, part in enumerate(parts):
        backend.set_password(SERVICE, f"{key}#{index}", part)
    backend.set_password(SERVICE, key, str(len(parts)))
    _forget_chunks(backend, key, len(parts), previous)


def _forget_chunks(backend: Any, key: str, start: int, stop: int) -> None:
    for index in range(start, stop):
        _forget(backend, f"{key}#{index}")


def _forget(backend: Any, name: str) -> None:
    try:
        backend.delete_password(SERVICE, name)
    except Exception:
        pass


def _decoded(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _file_entries() -> dict[str, Any]:
    path = credentials_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _file_change(change: Callable[[dict[str, Any]], Any]) -> None:
    with store.lock():
        path = credentials_file()
        entries = _file_entries()
        change(entries)
        if entries:
            write_atomic(path, json.dumps(entries, indent=2))
        elif path.exists():
            path.unlink()


def _warn_once() -> None:
    global _warned
    if _warned or os.environ.get(BACKEND_ENV) or credentials_file().exists():
        return
    _warned = True
    print(
        f"ov: no system keyring available, so credentials are kept in {credentials_file()} "
        "(owner-only).",
        file=sys.stderr,
    )
