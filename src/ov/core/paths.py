from __future__ import annotations

import os
import re
import stat
import tempfile
import time
from pathlib import Path

HOME_ENV = "OV_HOME"
REPLACE_ATTEMPTS = 10
REPLACE_RETRY_SECONDS = 0.05

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def home() -> Path:
    override = os.environ.get(HOME_ENV)
    root = Path(override).expanduser() if override else Path.home() / ".ov"
    return _ensure(root)


def config_file() -> Path:
    return home() / "config.json"


def downloads_dir() -> Path:
    return _ensure(home() / "downloads")


def cache_dir() -> Path:
    return _ensure(home() / "cache")


def spec_dir() -> Path:
    return _ensure(home() / "spec")


def browser_profile_dir() -> Path:
    return _ensure(home() / "browser")


def agent_dir(*parts: str) -> Path:
    return _ensure(home().joinpath("agent", *parts))


def spec_file(base_url: str, group: str) -> Path:
    return spec_dir() / f"{slugify(base_url)}.{slugify(group)}.json"


def slugify(value: str) -> str:
    cleaned = _UNSAFE.sub("-", value.replace("https://", "").replace("http://", "")).strip("-")
    return cleaned.lower() or "default"


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path


def restrict(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def write_atomic(path: Path, text: str) -> None:
    descriptor, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        restrict(Path(temp))
        _replace_when_unlocked(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _replace_when_unlocked(source: str, target: Path) -> None:
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_RETRY_SECONDS)
