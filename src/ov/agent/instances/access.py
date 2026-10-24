from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from ov.agent.instances.http import open_client
from ov.core.errors import OvError, SessionExpired
from ov.core.paths import agent_dir, slugify, write_atomic
from ov.onevizion.client import Client

PRIVS_PATH = "/v3/privs"
SERVER_INFO_PATH = "/v3/server_info"
MAIN_PAGE_PATH = "/Default.do"
NO_PRIVILEGE = "NONE"
_EDITION = re.compile(r"platformEditionKey\s*=\s*'([A-Z_]+)'")

NEEDS: dict[str, tuple[tuple[str, str], ...]] = {
    "testSql": (("TEST_SQL", "R"),),
    "export": (("BPL_EXP_IMP", "R"),),
    "import": (("BPL_EXP_IMP", "A"),),
    "metadata": (("METADATA", "R"),),
    "dbSource": (("METADATA", "R"), ("DB_DOCS", "R")),
    "mcp": (("MCP_SERVER", "R"),),
}
LABELS = {
    "testSql": "Test SQL",
    "export": "component export",
    "import": "component import",
    "metadata": "schema metadata",
    "dbSource": "platform DB source",
    "mcp": "MCP server",
}
EDITIONS = {"STANDARD": "Standard", "ENTERPRISE": "Enterprise", "PREMIUM": "Premium", "AI_ENABLED": "AI Enabled"}
NOT_CHECKED = "access not checked yet"


class AccessError(Exception):
    pass


_checking: set[str] = set()
_errors: dict[str, str] = {}
_lock = threading.Lock()


def _file(alias: str) -> Path:
    return agent_dir("access") / f"{slugify(alias)}.json"


def load(alias: str) -> dict[str, Any] | None:
    path = _file(alias)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _has(granted: dict[str, str], group: str, letters: str) -> bool:
    priv = granted.get(group, NO_PRIVILEGE)
    return priv != NO_PRIVILEGE and all(letter in priv for letter in letters)


def _edition(client: Client) -> str | None:
    try:
        page = client.web_get(MAIN_PAGE_PATH, accept="text/html").text
    except SessionExpired:
        return None

    found = _EDITION.search(page)
    return found.group(1) if found else None


def _read(alias: str) -> dict[str, Any]:
    with open_client(alias) as client:
        granted = {row["security_group"]: row["priv"] for row in client.api("GET", PRIVS_PATH).json()}
        version = client.api("GET", SERVER_INFO_PATH).json().get("version")
        edition = _edition(client)

    previous = load(alias) or {}
    return {
        "checkedAt": int(time.time() * 1000),
        "version": version,
        "edition": edition or previous.get("edition"),
        **{name: all(_has(granted, group, letters) for group, letters in needs) for name, needs in NEEDS.items()},
    }


def check(alias: str) -> dict[str, Any]:
    with _lock:
        _checking.add(alias)
        _errors.pop(alias, None)
    try:
        found = _read(alias)
    except OvError as exc:
        with _lock:
            _errors[alias] = str(exc)
        raise AccessError(f"Could not check what your account can do on {alias}: {exc}") from None
    finally:
        with _lock:
            _checking.discard(alias)

    write_atomic(_file(alias), json.dumps(found))
    return found


def check_later(alias: str) -> None:
    def work() -> None:
        try:
            check(alias)
        except AccessError:
            return

    threading.Thread(target=work, daemon=True, name=f"access-{alias}").start()


def ensure(alias: str) -> dict[str, Any]:
    return load(alias) or check(alias)


def status(alias: str) -> dict[str, Any]:
    with _lock:
        checking, error = alias in _checking, _errors.get(alias)
    return {**(load(alias) or {}), "checking": checking, **({"error": error} if error else {})}


def allows(alias: str, capability: str) -> bool | None:
    found = load(alias)
    return None if found is None else bool(found[capability])


def describe(alias: str) -> str:
    found = load(alias)
    if found is None:
        return NOT_CHECKED

    platform = " ".join(
        part
        for part in (
            f"platform {found['version']}" if found.get("version") else "",
            f"{EDITIONS.get(found['edition'], found['edition'])} edition" if found.get("edition") else "",
        )
        if part
    )
    allowed = [label for name, label in LABELS.items() if found[name]]
    denied = [label for name, label in LABELS.items() if not found[name]]
    parts = [
        platform,
        f"can use {', '.join(allowed)}" if allowed else "",
        f"cannot use {', '.join(denied)}" if denied else "",
    ]
    return "; ".join(p for p in parts if p)
