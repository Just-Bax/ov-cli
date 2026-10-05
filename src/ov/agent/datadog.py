from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .. import credentials
from ..paths import agent_dir, write_atomic
from .graph import GraphError
from .ovproc import find_instance, host_of, instances

CREDENTIAL_KEY = "agent:datadog"
TIMEOUT_SECONDS = 30
RATE_LIMIT_WAIT_SECONDS = 2.0
MAX_RATE_LIMIT_WAIT_SECONDS = 10.0
PROBE_SECONDS = 300
MAX_LOG_LINES = 50
MAX_LOG_PAGE = 1000
MAX_EVENTS = 100
MONITORS_PAGE = 1000
HOSTS_PAGE = 1000
MONITOR_GROUPS = 5
MESSAGE_CHARS = 400
LOG_MESSAGE_CHARS = 2000
DETAIL_CHARS = 300
TITLE_CHARS = 200
ERROR_BODY_CHARS = 200
PATTERN_CHARS = 180
HEALTH_TTL_SECONDS = 60
HEALTH_WORKERS = 8
HEALTH_LOG_SAMPLE = 300
HEALTH_EVENTS = 15
HEALTH_ENDPOINTS = 8
CHART_POINTS = 60
EPOCH_MS_THRESHOLD = 10**11
NS_PER_MS = 1e6

SITES: dict[str, tuple[str, str]] = {
    "datadoghq.com": ("api.datadoghq.com", "app.datadoghq.com"),
    "us3.datadoghq.com": ("api.us3.datadoghq.com", "us3.datadoghq.com"),
    "us5.datadoghq.com": ("api.us5.datadoghq.com", "us5.datadoghq.com"),
    "datadoghq.eu": ("api.datadoghq.eu", "app.datadoghq.eu"),
    "ap1.datadoghq.com": ("api.ap1.datadoghq.com", "ap1.datadoghq.com"),
    "ap2.datadoghq.com": ("api.ap2.datadoghq.com", "ap2.datadoghq.com"),
    "ddog-gov.com": ("api.ddog-gov.com", "app.ddog-gov.com"),
}
DEFAULT_SITE = "datadoghq.com"

AREAS: dict[str, str] = {
    "logs": "logs_read_data",
    "metrics": "timeseries_query",
    "monitors": "monitors_read",
    "events": "events_read",
    "apm": "apm_read",
    "hosts": "hosts_read",
}
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
STATUS_MESSAGES = {
    401: "Datadog rejected the API key (wrong key, or a key for another site).",
    429: "Datadog rate limit reached. Try again in a minute.",
}
MONITOR_ORDER = {"Alert": 0, "Warn": 1, "No Data": 2}
QUIET_STATES = ("OK", "Ignored", "Skipped")

TRANSPORT: httpx.BaseTransport | None = None

_lock = threading.Lock()
_health_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


class DatadogError(Exception):
    pass


def site_of(value: str) -> str:
    text = value.strip().lower()
    if not text:
        return DEFAULT_SITE

    host = urlsplit(text if "://" in text else f"https://{text}").hostname
    for site, (api, app) in SITES.items():
        if host in (site, api, app):
            return site

    longest_first = sorted(SITES, key=len, reverse=True)
    for site in longest_first:
        if host and host.endswith("." + site):
            return site

    raise DatadogError(f"Unknown Datadog site: {value}")


def app_url(site: str) -> str:
    return f"https://{SITES[site][1]}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _state_file() -> Path:
    return agent_dir() / "datadog.json"


def load_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatadogError(f"Cannot read the Datadog settings in {path}: {exc}") from None
    if isinstance(data, dict):
        return data

    raise DatadogError(f"The Datadog settings in {path} are not a JSON object.")


def _save_state(state: dict[str, Any]) -> None:
    with _lock:
        write_atomic(_state_file(), json.dumps(state, indent=2))


def _stored(state: dict[str, Any], key: str) -> Any:
    if key not in state:
        raise DatadogError(f"The Datadog settings have no {key}. Reconnect Datadog in Settings > Integrations.")
    return state[key]


def _field(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise DatadogError(f"Datadog returned a response without {key}.")
    return data[key]


def _keys() -> tuple[str, str] | None:
    secrets = credentials.get(CREDENTIAL_KEY)
    if secrets is None:
        return None

    if not secrets.get("api_key") or not secrets.get("app_key"):
        raise DatadogError("The stored Datadog keys are incomplete. Reconnect Datadog in Settings > Integrations.")
    return str(secrets["api_key"]), str(secrets["app_key"])


def connected() -> bool:
    return "site" in load_state() and _keys() is not None


def permissions() -> dict[str, bool]:
    state = load_state()
    if "site" not in state:
        return dict.fromkeys(AREAS, False)

    stored = _stored(state, "permissions")
    return {area: bool(stored[area]) for area in AREAS}


class Client:
    def __init__(self, site: str, api_key: str, app_key: str) -> None:
        self.site = site
        self._http = httpx.Client(
            base_url=f"https://{SITES[site][0]}",
            headers={
                "DD-API-KEY": api_key,
                "DD-APPLICATION-KEY": app_key,
                "Accept": "application/json",
            },
            timeout=TIMEOUT_SECONDS,
            transport=TRANSPORT,
        )

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: Any) -> None:
        self._http.close()

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DatadogError(f"Could not reach Datadog: {exc}") from None

    def call(self, method: str, path: str, area: str = "", **kwargs: Any) -> Any:
        response = self._send(method, path, **kwargs)
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            time.sleep(_rate_limit_wait(response))
            response = self._send(method, path, **kwargs)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise DatadogError(_explain(response, area))
        return response.json() if response.content else {}


def _rate_limit_wait(response: httpx.Response) -> float:
    reset = response.headers.get("X-RateLimit-Reset", "")
    wait = float(reset) if reset.replace(".", "", 1).isdigit() else RATE_LIMIT_WAIT_SECONDS
    return min(wait, MAX_RATE_LIMIT_WAIT_SECONDS)


def _explain(response: httpx.Response, area: str) -> str:
    code = response.status_code
    if code in STATUS_MESSAGES:
        return STATUS_MESSAGES[code]

    if code == httpx.codes.FORBIDDEN:
        need = f" It needs the {AREAS[area]} scope." if area in AREAS else ""
        return f"Datadog refused this request: the application key may not allow it.{need}"

    return f"Datadog returned {code}: {_error_detail(response)}"


def _error_detail(response: httpx.Response) -> str:
    try:
        errors = response.json().get("errors") or []
    except ValueError:
        return response.text[:ERROR_BODY_CHARS]

    detail = "; ".join(e if isinstance(e, str) else e.get("detail", str(e)) for e in errors)
    return detail or response.text[:ERROR_BODY_CHARS]


def client() -> Client:
    state = load_state()
    keys = _keys()
    if "site" not in state or keys is None:
        raise DatadogError("Datadog is not connected. Connect it in Settings > Integrations.")
    return Client(state["site"], *keys)


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
        "apm": ("POST", "/api/v2/spans/events/search", {"json": _spans_body("*", "now-15m", "now", 1)}),
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
            "apiKeyLast4": api_key[-4:],
            "appKeyLast4": app_key[-4:],
            "permissions": found,
            "checkedAt": _now_ms(),
            "error": None,
        }
    )
    _save_state(state)
    _health_cache.clear()
    return status()


def retest() -> dict[str, Any]:
    state = load_state()
    keys = _keys()
    if "site" not in state or keys is None:
        raise DatadogError("Datadog is not connected. Connect it in Settings > Integrations.")

    try:
        state["permissions"] = check(state["site"], *keys)
        state["error"] = None
    except DatadogError as exc:
        state["error"] = str(exc)
    state["checkedAt"] = _now_ms()
    _save_state(state)
    _health_cache.clear()
    return status()


def disconnect() -> dict[str, Any]:
    credentials.delete(CREDENTIAL_KEY)
    _save_state({"matches": load_state().get("matches", {})})
    _health_cache.clear()
    return status()


def status() -> dict[str, Any]:
    state = load_state()
    on = connected()
    site = state.get("site", DEFAULT_SITE)
    private = ("apiKeyLast4", "appKeyLast4", "checkedAt", "error")
    details = {key: _stored(state, key) for key in private} if on else dict.fromkeys(private)

    return {
        "connected": on,
        "site": site,
        "appUrl": app_url(site),
        **details,
        "permissions": permissions() if on else dict.fromkeys(AREAS, False),
        "matches": state.get("matches", {}),
        "sites": [{"id": s, "app": SITES[s][1]} for s in SITES],
        "scopes": SCOPES,
    }


def save_matches(matches: dict[str, str]) -> dict[str, Any]:
    state = load_state()
    state["matches"] = {alias: value.strip() for alias, value in matches.items() if value.strip()}
    _save_state(state)
    _health_cache.clear()
    return status()


def filter_for(alias: str) -> str:
    matches = load_state().get("matches", {})
    if alias in matches:
        return matches[alias]

    found = find_instance(alias)
    if found is None:
        raise DatadogError(f"No signed-in instance matches {alias}.")

    tenants_last = sorted(
        (i for i in instances() if i["host"] == found["host"] and i["alias"] in matches),
        key=lambda i: bool(i["tenant"]),
    )
    return matches[tenants_last[0]["alias"]] if tenants_last else ""


_HOSTS = re.compile(r"^host:\(([^()]+)\)$")
_ONE_HOST = re.compile(r"^host:([^\s*()]+)$")


def hosts_in(scope: str) -> list[str] | None:
    text = scope.strip()
    many = _HOSTS.match(text)
    if many:
        return [h.strip() for h in many.group(1).split(" OR ") if h.strip()]

    one = _ONE_HOST.match(text)
    return [one.group(1)] if one else None


def scope_of(hosts: list[str]) -> str:
    hosts = sorted(dict.fromkeys(h.strip() for h in hosts if h.strip()))
    if not hosts:
        return ""
    return f"host:{hosts[0]}" if len(hosts) == 1 else f"host:({' OR '.join(hosts)})"


def role_of(host: str) -> str:
    first = host.split(".")[0].lower()
    words: list[str] = []
    for part in re.split(r"[-_]", first):
        if part.isalpha():
            words.append(part)
            continue
        leading_letters = re.sub(r"[^a-z].*", "", part)
        if leading_letters and not words:
            words.append(leading_letters)
        break

    return "-".join(words) or first


def with_role(scope: str, role: str | None) -> str:
    if not role or role == "all":
        return scope

    hosts = hosts_in(scope)
    if hosts is None:
        raise DatadogError("This instance's Datadog filter is not a list of servers, so it has no roles.")

    picked = [h for h in hosts if role_of(h) == role.lower()]
    if not picked:
        roles = ", ".join(sorted({role_of(h) for h in hosts}))
        raise DatadogError(f"No {role} servers. This instance has: {roles}.")

    return scope_of(picked)


def _instance_label(website: str) -> str:
    return website.split(":")[0].split(".")[0].lower()


def owner_of(host: str, instances_by_label: dict[str, str], websites: dict[str, str]) -> str | None:
    name = host.lower()
    if name in websites:
        return websites[name]

    domain_parts = name.split(".")[1:]
    owners = [
        (label, alias)
        for label, alias in instances_by_label.items()
        if any(p == label or p.startswith(label + "-") for p in domain_parts)
    ]
    return max(owners, key=lambda owner: len(owner[0]))[1] if owners else None


def _all_hosts(dd: Client) -> list[str]:
    if not permissions()["hosts"]:
        raise DatadogError("Finding servers needs the hosts_read scope on the application key.")

    names: list[str] = []
    while True:
        data = dd.call("GET", "/api/v1/hosts", "hosts", params={"count": HOSTS_PAGE, "start": len(names)})
        rows = _field(data, "host_list")
        names += [row["name"] for row in rows]
        if not rows or len(names) >= _field(data, "total_matching"):
            return sorted(set(names))


def _main_instances() -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for inst in sorted(instances(), key=lambda i: bool(i["tenant"])):
        seen.setdefault(inst["host"], inst)
    return list(seen.values())


def discover() -> dict[str, Any]:
    with client() as dd:
        names = _all_hosts(dd)

    mains = _main_instances()
    by_label = {_instance_label(i["host"]): i["alias"] for i in mains}
    websites = {i["host"].split(":")[0].lower(): i["alias"] for i in mains}
    hosts = []
    groups: dict[str, list[str]] = {}
    for name in names:
        alias = owner_of(name, by_label, websites)
        hosts.append({"name": name, "role": role_of(name), "alias": alias})
        if alias:
            groups.setdefault(alias, []).append(name)

    return {"hosts": hosts, "groups": {k: scope_of(v) for k, v in groups.items()}}


_RELATIVE = re.compile(r"^now(?:\s*-\s*(\d+)\s*([smhdw]))?$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _epoch_ms(number: float) -> float:
    return number if number > EPOCH_MS_THRESHOLD else number * 1000


def to_ms(value: Any, default: str) -> int:
    text = str(value or default).strip().lower()
    relative = _RELATIVE.match(text)
    if relative:
        back = int(relative.group(1) or 0) * _UNITS[relative.group(2) or "s"]
        return int((time.time() - back) * 1000)

    if text.isdigit():
        return int(_epoch_ms(int(text)))

    try:
        parsed = datetime.fromisoformat(text.replace("z", "+00:00"))
    except ValueError:
        raise DatadogError(f'Not a time: "{value}". Use now-2h, an ISO date, or epoch.') from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def iso(ms: int | float | str | None) -> str:
    if ms is None or ms == "":
        return ""
    if isinstance(ms, str) and not ms.replace(".", "", 1).isdigit():
        return ms[:19].replace("T", " ")
    seconds = _epoch_ms(float(ms)) / 1000
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")


def combine(scope: str, query: str) -> str:
    parts = [p for p in (scope.strip(), query.strip()) if p]
    if len(parts) == 2:
        return f"({parts[0]}) {parts[1]}"
    return parts[0] if parts else "*"


def logs_link(site: str, query: str, start: int, end: int) -> str:
    return f"{app_url(site)}/logs?query={quote(query)}&from_ts={start}&to_ts={end}&live=false"


def search_logs(query: str, start: int, end: int, limit: int) -> list[dict[str, Any]]:
    body = {
        "filter": {"from": str(start), "to": str(end), "query": query},
        "page": {"limit": max(1, min(limit, MAX_LOG_PAGE))},
        "sort": "-timestamp",
    }
    with client() as dd:
        data = dd.call("POST", "/api/v2/logs/events/search", "logs", json=body)
    return [_log_row(row) for row in _field(data, "data")]


def _log_row(row: dict[str, Any]) -> dict[str, Any]:
    attrs = _field(row, "attributes")
    inner = attrs.get("attributes") or {}
    error = inner.get("error") if isinstance(inner.get("error"), dict) else {}

    return {
        "time": iso(attrs.get("timestamp")),
        "host": attrs.get("host") or "",
        "service": attrs.get("service") or "",
        "status": attrs.get("status") or "",
        "message": str(attrs.get("message") or error.get("message") or "")[:LOG_MESSAGE_CHARS],
        "errorKind": str(error.get("kind") or ""),
    }


_NOISE = (
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<hash>"),
    (re.compile(r"'[^']*'"), "'<v>'"),
    (re.compile(r'"[^"]*"'), '"<v>"'),
    (re.compile(r"\d+(?:[.:,]\d+)*"), "<n>"),
)


def pattern_of(message: str) -> str:
    text = message.strip().splitlines()[0] if message.strip() else ""
    for regex, token in _NOISE:
        text = regex.sub(token, text)
    return re.sub(r"\s+", " ", text)[:PATTERN_CHARS]


def top_patterns(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    sample: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = pattern_of(f"{row['errorKind']} {row['message']}" if row["errorKind"] else row["message"])
        if not key:
            continue
        counts[key] += 1
        sample.setdefault(key, row)

    return [
        {
            "pattern": key,
            "count": n,
            "example": sample[key]["message"][:MESSAGE_CHARS],
            "service": sample[key]["service"],
            "last": sample[key]["time"],
        }
        for key, n in counts.most_common(limit)
    ]


def log_timeseries(query: str, start: int, end: int, interval: str) -> list[dict[str, Any]]:
    body = {
        "compute": [{"aggregation": "count", "type": "timeseries", "interval": interval}],
        "filter": {"from": str(start), "to": str(end), "query": query},
    }
    with client() as dd:
        data = dd.call("POST", "/api/v2/logs/analytics/aggregate", "logs", json=body)

    buckets = _field(_field(data, "data"), "buckets")
    return _series(_field(buckets[0], "computes").get("c0", [])) if buckets else []


def metric_scope(scope: str) -> str:
    hosts = hosts_in(scope)
    if hosts:
        return f"host:{hosts[0]}" if len(hosts) == 1 else f"host IN ({','.join(hosts)})"

    tags = [t for t in scope.split() if ":" in t and not t.startswith(("-", "("))]
    return ",".join(tags) or "*"


def query_metric(query: str, start: int, end: int) -> list[dict[str, Any]]:
    params = {"from": start // 1000, "to": end // 1000, "query": query}
    with client() as dd:
        data = dd.call("GET", "/api/v1/query", "metrics", params=params)
    return [_metric_series(series, query) for series in _field(data, "series")]


def _metric_series(series: dict[str, Any], query: str) -> dict[str, Any]:
    points = [
        {"t": int(p[0]), "v": float(p[1])} for p in series.get("pointlist") or [] if len(p) > 1 and p[1] is not None
    ]
    units = series.get("unit") or []
    unit = units[0] if units and units[0] else {}

    return {
        "name": series.get("expression") or series.get("metric") or query,
        "scope": series.get("scope") or "",
        "unit": unit.get("short_name") or "",
        "points": points,
    }


def summarize_series(series: dict[str, Any], samples: int = 12) -> str:
    values = [p["v"] for p in series["points"]]
    if not values:
        return f"{series['name']} [{series['scope']}]: no data"

    step = max(1, len(series["points"]) // samples)
    sampled = ", ".join(f"{iso(p['t'])[11:16]}={_num(p['v'])}" for p in series["points"][::step][:samples])
    unit = f" {series['unit']}" if series["unit"] else ""

    return (
        f"{series['name']} [{series['scope']}]{unit}: min {_num(min(values))}, "
        f"avg {_num(sum(values) / len(values))}, max {_num(max(values))}, "
        f"latest {_num(values[-1])}\n  {sampled}"
    )


def _num(value: float) -> str:
    if abs(value) >= 1e9:
        return f"{value / 1e9:.2f}G"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.2f}M"
    if abs(value) >= 1e3:
        return f"{value / 1e3:.2f}k"
    return f"{value:.3g}"


def monitors_for(scope: str, include_ok: bool) -> list[dict[str, Any]]:
    params = {"group_states": "alert,warn,no data", "page": 0, "page_size": MONITORS_PAGE}
    with client() as dd:
        data = dd.call("GET", "/api/v1/monitor", "monitors", params=params)

    needles = _needles(scope)
    rows = [_monitor_row(mon) for mon in data if _mentions(mon, needles)]
    if not include_ok:
        rows = [m for m in rows if m["state"] not in QUIET_STATES]
    return sorted(rows, key=lambda m: (MONITOR_ORDER.get(m["state"], len(MONITOR_ORDER)), m["name"]))


def _needles(scope: str) -> list[str]:
    hosts = hosts_in(scope)
    if hosts:
        return [h.lower() for h in hosts]

    values = [t.split(":", 1)[1].rstrip("*").lower() for t in scope.split() if ":" in t]
    return [v for v in values if v]


def _monitor_groups(mon: dict[str, Any]) -> list[str]:
    return list(((mon.get("state") or {}).get("groups") or {}).keys())


def _mentions(mon: dict[str, Any], needles: list[str]) -> bool:
    if not needles:
        return True

    haystack = " ".join([str(mon.get("query", "")), *(mon.get("tags") or []), *_monitor_groups(mon)]).lower()
    return any(n in haystack for n in needles)


def _monitor_row(mon: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _field(mon, "id"),
        "name": mon.get("name") or "",
        "state": str(mon.get("overall_state") or "Unknown"),
        "type": mon.get("type") or "",
        "groups": _monitor_groups(mon)[:MONITOR_GROUPS],
        "message": str(mon.get("message") or "")[:DETAIL_CHARS],
    }


def events_for(query: str, start: int, end: int, limit: int) -> list[dict[str, Any]]:
    params = {
        "filter[query]": query,
        "filter[from]": str(start),
        "filter[to]": str(end),
        "page[limit]": max(1, min(limit, MAX_EVENTS)),
        "sort": "-timestamp",
    }
    with client() as dd:
        data = dd.call("GET", "/api/v2/events", "events", params=params)
    return [_event_row(row) for row in _field(data, "data")]


def _event_row(row: dict[str, Any]) -> dict[str, Any]:
    attrs = _field(row, "attributes")
    inner = attrs.get("attributes") or {}

    return {
        "time": iso(attrs.get("timestamp") or inner.get("timestamp")),
        "title": str(inner.get("title") or attrs.get("title") or "")[:TITLE_CHARS],
        "message": str(attrs.get("message") or inner.get("message") or "")[:DETAIL_CHARS],
        "source": str(inner.get("source_type_name") or inner.get("source") or ""),
        "status": str(inner.get("status") or ""),
    }


def _spans_body(query: str, start: str, end: str, limit: int) -> dict[str, Any]:
    return {
        "data": {
            "type": "search_request",
            "attributes": {
                "filter": {"from": start, "to": end, "query": query},
                "page": {"limit": limit},
                "sort": "-timestamp",
            },
        }
    }


def _computes(attrs: dict[str, Any]) -> dict[str, Any]:
    compute = attrs.get("compute") or attrs.get("computes")
    if compute is None:
        raise DatadogError("Datadog returned an APM bucket without computed values.")
    return compute


def slow_endpoints(query: str, start: int, end: int, limit: int = 10) -> list[dict[str, Any]]:
    by_p95 = {"aggregation": "pc95", "metric": "@duration", "order": "desc", "type": "measure"}
    body = {
        "data": {
            "type": "aggregate_request",
            "attributes": {
                "compute": [
                    {"aggregation": "pc95", "metric": "@duration", "type": "total"},
                    {"aggregation": "count", "type": "total"},
                ],
                "filter": {"from": str(start), "to": str(end), "query": query},
                "group_by": [{"facet": "resource_name", "limit": limit, "sort": by_p95}],
            },
        }
    }
    with client() as dd:
        data = dd.call("POST", "/api/v2/spans/analytics/aggregate", "apm", json=body)
    return [_endpoint_row(bucket) for bucket in _field(data, "data")]


def _endpoint_row(bucket: dict[str, Any]) -> dict[str, Any]:
    attrs = _field(bucket, "attributes")
    compute = _computes(attrs)

    return {
        "resource": str((attrs.get("by") or {}).get("resource_name") or "?"),
        "p95Ms": round(float(compute.get("c0") or 0) / NS_PER_MS, 1),
        "count": int(compute.get("c1") or 0),
    }


def error_spans(query: str, start: int, end: int, limit: int) -> list[dict[str, Any]]:
    body = _spans_body(combine(query, "status:error"), str(start), str(end), limit)
    with client() as dd:
        data = dd.call("POST", "/api/v2/spans/events/search", "apm", json=body)
    return [_error_span_row(row) for row in _field(data, "data")]


def _error_span_row(row: dict[str, Any]) -> dict[str, Any]:
    attrs = _field(row, "attributes")
    custom = attrs.get("custom") or attrs.get("attributes") or {}
    error = custom.get("error") if isinstance(custom.get("error"), dict) else {}

    return {
        "time": iso(attrs.get("start_timestamp") or attrs.get("timestamp")),
        "service": attrs.get("service") or "",
        "resource": attrs.get("resource_name") or "",
        "error": str(error.get("message") or error.get("type") or "")[:DETAIL_CHARS],
        "trace": attrs.get("trace_id") or "",
    }


RANGES = {"1h": (3600, "1m"), "24h": (86400, "30m"), "7d": (604800, "6h")}
METRICS = [
    ("cpu", "CPU", "avg:system.cpu.user{%s} by {host}", "%"),
    ("load", "Load (per core)", "avg:system.load.norm.1{%s} by {host}", ""),
    ("memory", "Memory usable", "avg:system.mem.pct_usable{%s} by {host}*100", "%"),
    ("disk", "Disk in use", "max:system.disk.in_use{%s} by {host}*100", "%"),
    ("heap", "JVM heap", "avg:jvm.heap_memory{%s} by {host}", "B"),
]


def health(alias: str, range_key: str, ov_side: Callable[[], Any] | None = None) -> dict[str, Any]:
    if range_key not in RANGES:
        raise DatadogError(f"Unknown range {range_key}. Use one of: {', '.join(RANGES)}.")

    key = (alias, range_key)
    cached = _health_cache.get(key)
    if cached and time.time() - cached[0] < HEALTH_TTL_SECONDS:
        return cached[1]

    scope = filter_for(alias)
    seconds, interval = RANGES[range_key]
    end = _now_ms()
    start = end - seconds * 1000

    report = _health_report(alias, range_key, scope, start, end)
    if not scope:
        report["errors"]["scope"] = "This instance is not matched to Datadog yet."
        return report

    jobs = _health_jobs(scope, start, end, interval)
    if ov_side is not None:
        jobs.append(("onevizion", ov_side))

    _run_jobs(report, jobs)
    _add_metrics(report, scope)
    _health_cache[key] = (time.time(), report)
    return report


def _health_report(alias: str, range_key: str, scope: str, start: int, end: int) -> dict[str, Any]:
    site = load_state().get("site", DEFAULT_SITE)
    base = app_url(site)

    return {
        "instance": alias,
        "range": range_key,
        "scope": scope,
        "from": start,
        "to": end,
        "appUrl": base,
        "links": {
            "logs": logs_link(site, combine(scope, "status:error"), start, end),
            "monitors": f"{base}/monitors/manage",
            "apm": f"{base}/apm/traces?query={quote(scope)}",
            "events": f"{base}/event/explorer?query={quote(scope)}",
        },
        "errors": {},
    }


def _error_count(query: str, start: int, end: int, interval: str) -> float:
    return sum(p["v"] for p in log_timeseries(query, start, end, interval))


def _health_jobs(scope: str, start: int, end: int, interval: str) -> list[tuple[str, Callable[[], Any]]]:
    allowed = permissions()
    errors_query = combine(scope, "status:error")
    previous_start = start - (end - start)
    jobs: list[tuple[str, Callable[[], Any]]] = []
    if allowed["monitors"]:
        jobs.append(("monitors", partial(monitors_for, scope, include_ok=True)))

    if allowed["logs"]:
        jobs += [
            ("errorSeries", partial(log_timeseries, errors_query, start, end, interval)),
            ("logSeries", partial(log_timeseries, scope, start, end, interval)),
            ("previousErrors", partial(_error_count, errors_query, previous_start, start, interval)),
            ("topErrors", lambda: top_patterns(search_logs(errors_query, start, end, HEALTH_LOG_SAMPLE))),
        ]

    if allowed["events"]:
        jobs.append(("events", partial(events_for, scope, start, end, HEALTH_EVENTS)))

    if allowed["apm"]:
        jobs += [
            ("slowEndpoints", partial(slow_endpoints, scope, start, end, HEALTH_ENDPOINTS)),
            ("traffic", partial(traffic, scope, start, end, interval)),
        ]

    if allowed["metrics"]:
        tags = metric_scope(scope)
        jobs += [
            (f"metric:{name}", partial(_metric_card, title, template % tags, unit, start, end))
            for name, title, template, unit in METRICS
        ]

    return jobs


def _run_jobs(report: dict[str, Any], jobs: list[tuple[str, Callable[[], Any]]]) -> None:
    def run(name: str, fn: Callable[[], Any]) -> None:
        try:
            report[name] = fn()
        except (DatadogError, GraphError) as exc:
            report["errors"][name] = str(exc)

    with ThreadPoolExecutor(max_workers=HEALTH_WORKERS) as pool:
        list(pool.map(lambda job: run(*job), jobs))


def _add_metrics(report: dict[str, Any], scope: str) -> None:
    cards = {name: report.pop(f"metric:{name}", None) for name, *_ in METRICS}
    report["metrics"] = [card for card in cards.values() if card]
    names = hosts_in(scope) or sorted({h for card in report["metrics"] for h in card["byHost"]})
    report["servers"] = [
        {"host": name, "role": role_of(name), **{key: _latest(card, name) for key, card in cards.items()}}
        for name in names
    ]


def _latest(card: dict[str, Any] | None, host: str) -> float | None:
    if card is None or host not in card["byHost"]:
        return None
    return card["byHost"][host]["latest"]


def _metric_card(title: str, query: str, unit: str, start: int, end: int) -> dict[str, Any] | None:
    series = query_metric(query, start, end)
    points: dict[int, list[float]] = {}
    for s in series:
        for p in s["points"]:
            points.setdefault(p["t"], []).append(p["v"])

    merged = [{"t": t, "v": sum(v) / len(v)} for t, v in sorted(points.items())]
    if not merged:
        return None

    return {
        "byHost": _by_host(series),
        "title": title,
        "query": query,
        "unit": unit,
        "points": downsample(merged),
        "max": max(p["v"] for p in merged),
        "hosts": len(series),
    }


def _by_host(series: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_host = {}
    for s in series:
        name = next((p.split(":", 1)[1] for p in s["scope"].split(",") if p.startswith("host:")), None)
        if name and s["points"]:
            by_host[name] = {"latest": s["points"][-1]["v"], "max": max(p["v"] for p in s["points"])}
    return by_host


def downsample(points: list[dict[str, float]], buckets: int = CHART_POINTS) -> list[dict[str, float]]:
    if len(points) <= buckets:
        return points

    size = len(points) / buckets
    out = []
    for i in range(buckets):
        chunk = points[int(i * size) : int((i + 1) * size)]
        out.append({"t": chunk[0]["t"], "v": sum(p["v"] for p in chunk) / len(chunk)})
    return out


def _stamp_ms(stamp: str | int) -> int:
    if isinstance(stamp, str) and not stamp.isdigit():
        return to_ms(stamp, "now")
    return int(stamp)


def _series(points: list[dict[str, Any]]) -> list[dict[str, float]]:
    return [{"t": _stamp_ms(_field(p, "time")), "v": float(p.get("value") or 0)} for p in points]


def _span_series(query: str, start: int, end: int, interval: str) -> dict[str, Any]:
    timeseries = {"type": "timeseries", "interval": interval}
    body = {
        "data": {
            "type": "aggregate_request",
            "attributes": {
                "compute": [
                    {"aggregation": "count", **timeseries},
                    {"aggregation": "pc95", "metric": "@duration", **timeseries},
                ],
                "filter": {"from": str(start), "to": str(end), "query": query},
            },
        }
    }
    with client() as dd:
        data = dd.call("POST", "/api/v2/spans/analytics/aggregate", "apm", json=body)

    buckets = _field(data, "data")
    if not buckets:
        return {"requests": [], "p95Ms": []}

    compute = _computes(_field(buckets[0], "attributes"))
    latency = [{"t": p["t"], "v": p["v"] / NS_PER_MS} for p in _series(compute.get("c1", []))]
    return {"requests": _series(compute.get("c0", [])), "p95Ms": latency}


def traffic(query: str, start: int, end: int, interval: str) -> dict[str, Any]:
    entry_spans = _span_series(combine(query, "@span.kind:server"), start, end, interval)
    if any(p["v"] for p in entry_spans["requests"]):
        return entry_spans
    return _span_series(query, start, end, interval)


def resolve_scope(instance: str | None, current: str, role: str | None = None) -> tuple[str, str]:
    target = (instance or current).strip()
    if not target:
        return "", ""

    found = find_instance(target)
    if found is None:
        return host_of(target), ""

    scope = filter_for(found["alias"])
    if not scope:
        raise DatadogError(
            f"{found['host']} is not matched to Datadog yet. Match it in Settings > "
            "Integrations > Datadog, or pass a query with its host or service tag."
        )

    return found["alias"], with_role(scope, role)
