from __future__ import annotations

import os
import re
import stat
from pathlib import Path

HOME_ENV = "OV_HOME"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def home() -> Path:
    override = os.environ.get(HOME_ENV)
    root = Path(override).expanduser() if override else Path.home() / ".ov"
    root.mkdir(parents=True, exist_ok=True)
    return root


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


def spec_file(base_url: str, group: str) -> Path:
    return spec_dir() / f"{slugify(base_url)}.{slugify(group)}.json"


def slugify(value: str) -> str:
    """Turn a base URL or group name into one safe path segment."""
    cleaned = _UNSAFE.sub("-", value.replace("https://", "").replace("http://", "")).strip("-")
    return cleaned.lower() or "default"


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def restrict(path: Path) -> None:
    """Make a file owner-readable only. On Windows this only clears the read-only
    bit, so config.json is not protected from other accounts on that OS."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
