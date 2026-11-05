from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ov.agent.engine.cases import TRACKOR_HOST, form_url
from ov.agent.instances.http import open_client
from ov.agent.instances.ovproc import find_instance
from ov.agent.integrations.common import TimedCache
from ov.core.errors import OvError

MAINTENANCE_PATH = "/api/v3/trackor_types/Maintenance/trackors"
WEBSITE_FIELD = "Website.TRACKOR_KEY"
SERVER_FIELD = "Server.TRACKOR_KEY"
FIELDS = [
    "TRACKOR_KEY",
    "MNT_SUBJECT",
    "MNT_TYPE",
    "MNT_STATUS",
    "MNT_MAINTENANCE_START",
    "MNT_MAINTENANCE_END",
    "MNT_DURATION",
    "MNT_VERSION_TO_DEPLOY",
    "MNT_OWNER",
    WEBSITE_FIELD,
    SERVER_FIELD,
]
ROWS_PER_QUERY = 300
WINDOW_ZONE = ZoneInfo("America/New_York")
CACHE_SECONDS = 60
DAY_MS = 86_400_000
LOOKBACK_DAYS = 30
SERVER_NAME_PARTS = 2
DONE_STATUSES = ("Completed", "Cancelled")
SHOWN = 25

_OWNER = re.compile(r"\(([^()]+)\)\s*$")
_cache = TimedCache(CACHE_SECONDS)


class MaintenanceUnavailable(Exception):
    pass


def server_name(host: str) -> str:
    return ".".join(host.lower().split(".")[:SERVER_NAME_PARTS])


def _eastern_ms(value: str | None) -> int | None:
    if not value:
        return None
    return int(datetime.fromisoformat(value).replace(tzinfo=WINDOW_ZONE).timestamp() * 1000)


def _owner(value: str | None) -> str:
    if not value:
        return ""
    named = _OWNER.search(value)
    return named.group(1) if named else value


def _rows(client: Any, field: str, value: str) -> list[dict[str, Any]]:
    params = [
        ("fields", ",".join(FIELDS)),
        (field, value),
        ("sort", "MNT_MAINTENANCE_START:desc"),
        ("page", "1"),
        ("per_page", str(ROWS_PER_QUERY)),
    ]
    return client.api("GET", MAINTENANCE_PATH, params=params).json()


def _mine(row: dict[str, Any], host: str, servers: set[str]) -> bool:
    website = (row.get(WEBSITE_FIELD) or "").lower()
    if website:
        return website == host
    return server_name(row.get(SERVER_FIELD) or "") in servers


def _merge(rows: list[dict[str, Any]], host: str, servers: set[str]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not _mine(row, host, servers):
            continue

        key = row["TRACKOR_KEY"]
        item = found.setdefault(
            key,
            {
                "key": key,
                "url": form_url(row["TRACKOR_ID"], TRACKOR_HOST),
                "type": row.get("MNT_TYPE") or "",
                "status": row.get("MNT_STATUS") or "",
                "subject": row.get("MNT_SUBJECT") or "",
                "version": row.get("MNT_VERSION_TO_DEPLOY") or "",
                "owner": _owner(row.get("MNT_OWNER")),
                "start": _eastern_ms(row.get("MNT_MAINTENANCE_START")),
                "end": _eastern_ms(row.get("MNT_MAINTENANCE_END")),
                "downtimeMinutes": int(row["MNT_DURATION"]) if row.get("MNT_DURATION") else None,
                "servers": [],
            },
        )
        server = row.get(SERVER_FIELD)
        if server and server not in item["servers"]:
            item["servers"].append(server)

    return list(found.values())


def _relevant(item: dict[str, Any], since: int) -> bool:
    if item["start"] is None:
        return item["status"] not in DONE_STATUSES
    return item["start"] >= since


def maintenance_for(alias: str, hosts: list[str], end: int) -> dict[str, Any]:
    trackor = find_instance(TRACKOR_HOST)
    if trackor is None:
        raise MaintenanceUnavailable(f"Sign in to {TRACKOR_HOST} to see maintenance from OneTeam.")

    instance = find_instance(alias)
    if instance is None:
        raise MaintenanceUnavailable(f"No signed-in instance matches {alias}.")

    host = instance["host"].split(":")[0]
    key = (host, tuple(hosts), end)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    servers = {server_name(h) for h in hosts}
    labels = sorted({s.split(".", 1)[1] for s in servers if "." in s})
    try:
        with open_client(trackor["alias"]) as client, ThreadPoolExecutor(max_workers=len(labels) + 1) as pool:
            jobs = [pool.submit(_rows, client, WEBSITE_FIELD, host)]
            jobs += [pool.submit(_rows, client, SERVER_FIELD, label) for label in labels]
            rows = [row for job in jobs for row in job.result()]
    except OvError as exc:
        raise MaintenanceUnavailable(f"Could not read maintenance from {TRACKOR_HOST}: {exc}") from exc

    since = end - LOOKBACK_DAYS * DAY_MS
    items = [i for i in _merge(rows, host, servers) if _relevant(i, since)]
    items.sort(key=lambda i: i["start"] or end, reverse=True)
    result = {"items": items[:SHOWN], "webUrl": f"https://{TRACKOR_HOST}"}
    _cache.put(key, result)
    return result
