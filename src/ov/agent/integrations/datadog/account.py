from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from ov.agent.integrations.datadog.apm import spans_body
from ov.agent.integrations.datadog.connection import (
    AREAS,
    CREDENTIAL_KEY,
    DEFAULT_SITE,
    SERVICE,
    SITES,
    Client,
    DatadogError,
    app_url,
    clear_caches,
    connected,
    load_state,
    permissions,
    save_state,
    site_of,
    stored_keys,
)
from ov.agent.storage.db import now_ms
from ov.core import credentials

PROBE_SECONDS = 300
KEY_TAIL_CHARS = 4

SCOPES = [
    "logs_read_data",
    "logs_read_index_data",
    "metrics_read",
    "timeseries_query",
    "monitors_read",
    "events_read",
    "apm_read",
    "hosts_read",
]


def _probe_request(area: str) -> tuple[str, str, dict[str, Any]]:
    now = int(time.time())

    requests: dict[str, tuple[str, str, dict[str, Any]]] = {
        "logs": (
            "POST",
            "/api/v2/logs/events/search",
            {"json": {"filter": {"from": "now-15m", "to": "now", "query": "*"}, "page": {"limit": 1}}},
        ),
        "metrics": (
            "GET",
            "/api/v1/query",
            {"params": {"from": now - PROBE_SECONDS, "to": now, "query": "avg:system.load.1{*}"}},
        ),
        "monitors": ("GET", "/api/v1/monitor", {"params": {"page": 0, "page_size": 1}}),
        "events": (
            "GET",
            "/api/v2/events",
            {"params": {"filter[from]": "now-1h", "filter[to]": "now", "page[limit]": 1}},
        ),
        "apm": ("POST", "/api/v2/spans/events/search", {"json": spans_body("*", "now-15m", "now", 1)}),
        "hosts": ("GET", "/api/v1/hosts", {"params": {"count": 1}}),
    }

    return requests[area]


def _probe(dd: Client, area: str) -> bool:
    method, path, kwargs = _probe_request(area)
    try:
        dd.call(method, path, area, **kwargs)
    except DatadogError:
        return False
    return True


def _validate(dd: Client) -> None:
    try:
        valid = dd.call("GET", "/api/v1/validate").get("valid")
    except DatadogError:
        raise DatadogError(
            "Datadog rejected the API key. Check that it is copied whole and that the site "
            "matches where you log in to Datadog."
        ) from None

    if not valid:
        raise DatadogError("Datadog says the API key is not valid for this site.")


def check(site: str, api_key: str, app_key: str) -> dict[str, bool]:
    api_key, app_key = api_key.strip(), app_key.strip()
    if not api_key or not app_key:
        raise DatadogError("Both the API key and the application key are needed.")

    with Client(site, api_key, app_key) as dd:
        _validate(dd)
        with ThreadPoolExecutor(max_workers=len(AREAS)) as pool:
            found = dict(zip(AREAS, pool.map(partial(_probe, dd), AREAS), strict=True))

    if not any(found.values()):
        raise DatadogError(
            "The API key works, but the application key cannot read anything. Check that it is "
            "copied whole and has read scopes such as logs_read_data and monitors_read."
        )

    return found


def connect(site: str, api_key: str, app_key: str) -> dict[str, Any]:
    site = site_of(site)
    api_key, app_key = api_key.strip(), app_key.strip()
    found = check(site, api_key, app_key)
    credentials.put(CREDENTIAL_KEY, {"api_key": api_key, "app_key": app_key})

    state = load_state()
    state.update(
        {
            "site": site,
            "apiKeyLast4": api_key[-KEY_TAIL_CHARS:],
            "appKeyLast4": app_key[-KEY_TAIL_CHARS:],
            "permissions": found,
            "checkedAt": now_ms(),
            "error": None,
        }
    )
    save_state(state)
    clear_caches()
    return status()


def retest() -> dict[str, Any]:
    state = load_state()
    keys = stored_keys()
    if "site" not in state or keys is None:
        raise DatadogError("Datadog is not connected. Connect it in Settings > Integrations.")

    try:
        state["permissions"] = check(state["site"], *keys)
        state["error"] = None
    except DatadogError as exc:
        state["error"] = str(exc)

    state["checkedAt"] = now_ms()
    save_state(state)
    clear_caches()
    return status()


def disconnect() -> dict[str, Any]:
    credentials.delete(CREDENTIAL_KEY)
    state = load_state()
    save_state({"matches": state.get("matches", {}), "databases": state.get("databases", {})})
    clear_caches()
    return status()


def status() -> dict[str, Any]:
    state = load_state()
    on = connected()
    site = state.get("site", DEFAULT_SITE)
    private = ("apiKeyLast4", "appKeyLast4", "checkedAt", "error")
    details = SERVICE.details(state, on, private)

    return {
        "connected": on,
        "site": site,
        "appUrl": app_url(site),
        **details,
        "permissions": permissions() if on else dict.fromkeys(AREAS, False),
        "matches": state.get("matches", {}),
        "databases": state.get("databases", {}),
        "sites": [{"id": s, "app": SITES[s][1]} for s in SITES],
        "scopes": SCOPES,
    }


def save_matches(matches: dict[str, str]) -> dict[str, Any]:
    state = load_state()
    state["matches"] = {alias: value.strip() for alias, value in matches.items() if value.strip()}
    save_state(state)
    clear_caches()
    return status()


def save_databases(databases: dict[str, list[str]]) -> dict[str, Any]:
    state = load_state()
    picked = {alias: sorted({i.strip().lower() for i in ids if i.strip()}) for alias, ids in databases.items()}
    state["databases"] = {alias: ids for alias, ids in picked.items() if ids}
    save_state(state)
    clear_caches()
    return status()


def forget(alias: str) -> None:
    state = load_state()
    tables = [state.get("matches", {}), state.get("databases", {})]
    if not any(alias in table for table in tables):
        return

    for table in tables:
        table.pop(alias, None)

    save_state(state)
    clear_caches()
