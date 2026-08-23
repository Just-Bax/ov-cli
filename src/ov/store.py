from __future__ import annotations

import json
from typing import Any

from .paths import config_file, restrict

SESSIONS_KEY = "sessions"
CURRENT_KEY = "current"

LEGACY_SESSION_KEY = "session"
LEGACY_BASE_URL_KEY = "base_url"


def read() -> dict[str, Any]:
    path = config_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return _migrated(data) if isinstance(data, dict) else {}


def _migrated(data: dict[str, Any]) -> dict[str, Any]:
    """Fold a pre-multi-instance config into the keyed layout.

    The old file held one unnamed session plus a base_url setting. Rewriting it
    on read rather than on upgrade means an old file keeps working whether or
    not anything writes afterwards.
    """
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


def update(**changes: Any) -> dict[str, Any]:
    """Merge keys into config.json, leaving every other key alone.

    Settings and every instance's credentials share one file, so a blind
    overwrite from either side would drop the other.
    """
    data = read()
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value

    path = config_file()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # The file holds live bearer tokens and session cookies, so it is
    # credentials, not just settings.
    restrict(path)
    return data
