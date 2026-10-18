from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ov.agent.instances.ovproc import find_instance, host_of, instances
from ov.agent.integrations.common import HttpClient, Service, TimedCache, explain, payload
from ov.agent.storage.db import now_ms
from ov.core import credentials

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
PATTERN_CHARS = 180
HEALTH_TTL_SECONDS = 60
DATABASE_TTL_SECONDS = 600
DATABASE_LOOKBACK_SECONDS = 3600
HEALTH_WORKERS = 8
HEALTH_LOG_SAMPLE = 300
HEALTH_EVENTS = 15
HEALTH_ENDPOINTS = 8
CHART_POINTS = 60
TOP_PATTERNS = 8
SUMMARY_SAMPLES = 12
SLOW_ENDPOINTS = 10
KEY_TAIL_CHARS = 4
ISO_SECONDS_CHARS = 19
ISO_CLOCK = slice(11, 16)
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

_health_cache = TimedCache(HEALTH_TTL_SECONDS)
_database_cache = TimedCache(DATABASE_TTL_SECONDS)


class DatadogError(Exception):
    pass


def clear_caches() -> None:
    _health_cache.clear()
    _database_cache.clear()


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


SERVICE = Service("Datadog", "datadog.json", "site", DatadogError)
load_state = SERVICE.load_state
_save_state = SERVICE.save_state
_stored = SERVICE.stored
_field = SERVICE.field


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
    return SERVICE.permissions(AREAS)


def _rate_limit_wait(response: httpx.Response) -> float:
    reset = response.headers.get("X-RateLimit-Reset", "")
    wait = float(reset) if reset.replace(".", "", 1).isdigit() else RATE_LIMIT_WAIT_SECONDS
    return min(wait, MAX_RATE_LIMIT_WAIT_SECONDS)


class Client(HttpClient):
    def __init__(self, site: str, api_key: str, app_key: str) -> None:
        super().__init__(
            SERVICE,
            f"https://{SITES[site][0]}",
            {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key, "Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
            transport=TRANSPORT,
            rate_limit_wait=_rate_limit_wait,
        )

    def call(self, method: str, path: str, area: str = "", **kwargs: Any) -> Any:
        response = self.send(method, path, **kwargs)
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise DatadogError(_explain(response, area))
        return payload(response)


def _errors_in(body: Any) -> str:
    errors = body.get("errors") or []
    return "; ".join(e if isinstance(e, str) else e.get("detail", str(e)) for e in errors)


def _explain(response: httpx.Response, area: str) -> str:
    need = f" It needs the {AREAS[area]} scope." if area in AREAS else ""
    forbidden = f"Datadog refused this request: the application key may not allow it.{need}"
    return explain(SERVICE, response, STATUS_MESSAGES, forbidden, _errors_in)


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
            "apiKeyLast4": api_key[-KEY_TAIL_CHARS:],
            "appKeyLast4": app_key[-KEY_TAIL_CHARS:],
            "permissions": found,
            "checkedAt": now_ms(),
            "error": None,
        }
    )
    _save_state(state)
    clear_caches()
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

    state["checkedAt"] = now_ms()
    _save_state(state)
    clear_caches()
    return status()


def disconnect() -> dict[str, Any]:
    credentials.delete(CREDENTIAL_KEY)
    _save_state({"matches": load_state().get("matches", {})})
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
        "sites": [{"id": s, "app": SITES[s][1]} for s in SITES],
        "scopes": SCOPES,
    }


def save_matches(matches: dict[str, str]) -> dict[str, Any]:
    state = load_state()
    state["matches"] = {alias: value.strip() for alias, value in matches.items() if value.strip()}
    _save_state(state)
    clear_caches()
    return status()


def forget(alias: str) -> None:
    state = load_state()
    matches = state.get("matches", {})
    if alias not in matches:
        return

    del matches[alias]
    _save_state(state)
    clear_caches()


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


def _owner_of_parts(parts: list[str], instances_by_label: dict[str, str]) -> str | None:
    owners = [
        (label, alias)
        for label, alias in instances_by_label.items()
        if any(p == label or p.startswith(label + "-") for p in parts)
    ]
    return max(owners, key=lambda owner: len(owner[0]))[1] if owners else None


def owner_of(host: str, instances_by_label: dict[str, str], websites: dict[str, str]) -> str | None:
    name = host.lower()
    if name in websites:
        return websites[name]
    return _owner_of_parts(name.split(".")[1:], instances_by_label)


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
        return ms[:ISO_SECONDS_CHARS].replace("T", " ")
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


def top_patterns(rows: list[dict[str, Any]], limit: int = TOP_PATTERNS) -> list[dict[str, Any]]:
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


def tag_filter(tag: str, values: list[str]) -> str:
    return f"{tag}:{values[0]}" if len(values) == 1 else f"{tag} IN ({','.join(values)})"


def metric_scope(scope: str, host_tag: str = "host") -> str:
    hosts = hosts_in(scope)
    if hosts:
        return tag_filter(host_tag, hosts)
    tags = [t for t in scope.split() if ":" in t and not t.startswith(("-", "("))]
    named = [f"{host_tag}:{t.removeprefix('host:')}" if t.startswith("host:") else t for t in tags]
    return ",".join(named) or "*"


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


def summarize_series(series: dict[str, Any], samples: int = SUMMARY_SAMPLES) -> str:
    values = [p["v"] for p in series["points"]]
    if not values:
        return f"{series['name']} [{series['scope']}]: no data"

    step = max(1, len(series["points"]) // samples)
    sampled = ", ".join(f"{iso(p['t'])[ISO_CLOCK]}={_num(p['v'])}" for p in series["points"][::step][:samples])
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


def monitors_for(scope: str, include_ok: bool, database_needles: list[str] | None = None) -> list[dict[str, Any]]:
    params = {"group_states": "alert,warn,no data", "page": 0, "page_size": MONITORS_PAGE}

    with client() as dd:
        data = dd.call("GET", "/api/v1/monitor", "monitors", params=params)

    needles = _needles(scope)
    exact = [re.compile(rf"(?<![\w.-]){re.escape(n.lower())}(?![\w-])") for n in database_needles or []]
    rows = [_monitor_row(mon) for mon in data if _mentions(mon, needles, exact)]
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


def _mentions(mon: dict[str, Any], needles: list[str], exact: list[re.Pattern[str]]) -> bool:
    if not needles and not exact:
        return True
    haystack = " ".join([str(mon.get("query", "")), *(mon.get("tags") or []), *_monitor_groups(mon)]).lower()
    return any(n in haystack for n in needles) or any(p.search(haystack) for p in exact)


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


def slow_endpoints(query: str, start: int, end: int, limit: int = SLOW_ENDPOINTS) -> list[dict[str, Any]]:
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
    ("cpu", "avg:system.cpu.user{%s} by {host}"),
    ("memory", "avg:system.mem.pct_usable{%s} by {host}*100"),
    ("disk", "max:system.disk.in_use{%s} by {host}*100"),
    ("load", "avg:system.load.norm.1{%s} by {host}"),
    ("heap", "avg:jvm.heap_memory{%s} by {host}"),
]
RDS_TAG = "dbinstanceidentifier"
RDS_ENGINE_TAG = "engine"
ORACLE_TAG = "server"
ORACLE_HOST_TAG = "ddagenthostname"
ORACLE_ENGINE = "oracle"
RDS_ENDPOINT_SUFFIX = ".rds.amazonaws.com"
ORACLE_PROBE = "avg:oracle.session_count{%s} by {server}"
RDS_PROBE = "avg:aws.rds.cpuutilization{*} by {dbinstanceidentifier,engine}"
DATABASE_METRICS = [
    ("cpu", RDS_TAG, "avg:aws.rds.cpuutilization{%(scope)s} by {dbinstanceidentifier}"),
    ("memory", RDS_TAG, "avg:aws.rds.freeable_memory{%(scope)s} by {dbinstanceidentifier}"),
    (
        "storage",
        RDS_TAG,
        "100 - 100 * avg:aws.rds.free_storage_space{%(scope)s} by {dbinstanceidentifier} / "
        "avg:aws.rds.total_storage_space{%(scope)s} by {dbinstanceidentifier}",
    ),
    ("connections", RDS_TAG, "avg:aws.rds.database_connections{%(scope)s} by {dbinstanceidentifier}"),
    ("readLatency", RDS_TAG, "avg:aws.rds.read_latency{%(scope)s} by {dbinstanceidentifier}*1000"),
    ("writeLatency", RDS_TAG, "avg:aws.rds.write_latency{%(scope)s} by {dbinstanceidentifier}*1000"),
    ("sessions", ORACLE_TAG, "max:oracle.session_limit_usage{%(scope)s} by {server}"),
    ("tablespace", ORACLE_TAG, "max:oracle.tablespace.in_use{%(scope)s} by {server}"),
]
SECTION_AREAS = {
    "monitors": "monitors",
    "logs": "logs",
    "traffic": "apm",
    "servers": "metrics",
    "database": "metrics",
    "events": "events",
}
AREA_WORDS = {"monitors": "monitors", "logs": "logs", "apm": "APM traces", "metrics": "metrics", "events": "events"}
SERVER_POINTS = 30


class Unavailable(DatadogError):
    pass


def window(range_key: str, end: int) -> tuple[int, str]:
    if range_key not in RANGES:
        raise DatadogError(f"Unknown range {range_key}. Use one of: {', '.join(RANGES)}.")
    seconds, interval = RANGES[range_key]
    return end - seconds * 1000, interval


def health_meta(alias: str, range_key: str) -> dict[str, Any]:
    end = now_ms()
    start, _ = window(range_key, end)
    scope = filter_for(alias)
    site = _stored(load_state(), "site")
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
            "metrics": f"{base}/infrastructure?filter={quote(scope)}",
        },
    }


def health_section(alias: str, range_key: str, section: str, end: int) -> dict[str, Any]:
    if section not in SECTION_AREAS:
        raise DatadogError(f"Unknown health section {section}.")

    key = (alias, range_key, section, end)
    cached = _health_cache.get(key)
    if cached is not None:
        return cached

    area = SECTION_AREAS[section]
    if not permissions()[area]:
        raise Unavailable(f"The Datadog application key cannot read {AREA_WORDS[area]}.")

    scope = filter_for(alias)
    if not scope:
        raise Unavailable("This instance has no Datadog servers picked yet.")

    start, interval = window(range_key, end)
    result = SECTION_READERS[section](alias, scope, start, end, interval)
    _health_cache.put(key, result)
    return result


def _parallel(jobs: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=HEALTH_WORKERS) as pool:
        futures = {name: pool.submit(fn) for name, fn in jobs.items()}
        return {name: future.result() for name, future in futures.items()}


def _monitors_section(alias: str, scope: str, _start: int, _end: int, _interval: str) -> dict[str, Any]:
    return {"monitors": monitors_for(scope, include_ok=True, database_needles=database_needles(alias))}


def _logs_section(_alias: str, scope: str, start: int, end: int, interval: str) -> dict[str, Any]:
    errors_query = combine(scope, "status:error")
    previous_start = start - (end - start)

    return _parallel(
        {
            "errorSeries": partial(log_timeseries, errors_query, start, end, interval),
            "logSeries": partial(log_timeseries, scope, start, end, interval),
            "previousErrors": partial(_error_count, errors_query, previous_start, start, interval),
            "topErrors": lambda: top_patterns(search_logs(errors_query, start, end, HEALTH_LOG_SAMPLE)),
        }
    )


def _traffic_section(_alias: str, scope: str, start: int, end: int, interval: str) -> dict[str, Any]:
    return _parallel(
        {
            "traffic": partial(traffic, scope, start, end, interval),
            "slowEndpoints": partial(slow_endpoints, scope, start, end, HEALTH_ENDPOINTS),
        }
    )


def _events_section(_alias: str, scope: str, start: int, end: int, _interval: str) -> dict[str, Any]:
    return {"events": events_for(scope, start, end, HEALTH_EVENTS)}


def _servers_section(_alias: str, scope: str, start: int, end: int, _interval: str) -> dict[str, Any]:
    tags = metric_scope(scope)
    found = _parallel({name: partial(query_metric, template % tags, start, end) for name, template in METRICS})
    names = hosts_in(scope) or sorted({_tag_of(s, "host") for series in found.values() for s in series} - {None})

    servers = []
    for name in names:
        metrics = {metric: _series_metric(found[metric], "host", name) for metric, _ in METRICS}
        servers.append({"host": name, "role": role_of(name), "metrics": {k: v for k, v in metrics.items() if v}})

    return {"servers": servers}


def _tag_of(series: dict[str, Any], tag: str) -> str | None:
    return next((p.split(":", 1)[1] for p in series["scope"].split(",") if p.startswith(f"{tag}:")), None)


def _series_metric(series: list[dict[str, Any]], tag: str, value: str) -> dict[str, Any] | None:
    mine = next((s for s in series if _tag_of(s, tag) == value and s["points"]), None)
    if mine is None:
        return None
    points = mine["points"]
    return {"latest": points[-1]["v"], "max": max(p["v"] for p in points), "points": downsample(points, SERVER_POINTS)}


def database_id(server: str) -> str:
    name = server.lower()
    return name.split(".")[0] if name.endswith(RDS_ENDPOINT_SUFFIX) else name


def _database_owner(alias: str, scope: str) -> Callable[[str], bool]:
    found = find_instance(alias)
    if found is None:
        raise DatadogError(f"No signed-in instance matches {alias}.")

    by_label = {_instance_label(i["host"]): i["alias"] for i in _main_instances()}
    mine = by_label.get(_instance_label(found["host"]))
    host_labels = {part for host in hosts_in(scope) or [] for part in host.lower().split(".")[1:]}
    return lambda ident: ident in host_labels or (mine is not None and _owner_of_parts([ident], by_label) == mine)


def _discover_databases(alias: str, scope: str) -> list[dict[str, str]]:
    end = now_ms()
    start = end - DATABASE_LOOKBACK_SECONDS * 1000
    agents = metric_scope(scope, ORACLE_HOST_TAG)
    jobs = {"rds": partial(query_metric, RDS_PROBE, start, end)}
    if agents != "*":
        jobs["oracle"] = partial(query_metric, ORACLE_PROBE % agents, start, end)

    probes = _parallel(jobs)

    found: dict[str, dict[str, str]] = {}
    for server in sorted({_tag_of(s, ORACLE_TAG) for s in probes.get("oracle", [])} - {None}):
        found[database_id(server)] = {"id": database_id(server), "engine": ORACLE_ENGINE, "endpoint": server.lower()}

    owns = _database_owner(alias, scope)
    for series in probes["rds"]:
        ident = (_tag_of(series, RDS_TAG) or "").lower()
        if not ident or (ident not in found and not owns(ident)):
            continue

        engine = _tag_of(series, RDS_ENGINE_TAG) or found.get(ident, {}).get("engine", "")
        found[ident] = {**found.get(ident, {"id": ident, "endpoint": ""}), "engine": engine}

    return [found[k] for k in sorted(found)]


def databases_for(alias: str) -> list[dict[str, str]]:
    scope = filter_for(alias)
    if not scope:
        return []

    key = (alias, scope)
    cached = _database_cache.get(key)
    if cached is not None:
        return cached

    found = _discover_databases(alias, scope)
    _database_cache.put(key, found)
    return found


def known_databases(alias: str) -> list[dict[str, str]]:
    if not connected() or not permissions()["metrics"]:
        return []
    return databases_for(alias)


def database_needles(alias: str) -> list[str]:
    needles = []
    for db in known_databases(alias):
        needles.append(f"{RDS_TAG}:{db['id']}")
        if db["endpoint"]:
            needles.append(db["endpoint"])
    return needles


def _database_section(alias: str, _scope: str, start: int, end: int, _interval: str) -> dict[str, Any]:
    databases = databases_for(alias)
    if not databases:
        raise Unavailable(
            "No database found for this instance in Datadog: its servers send no Oracle metrics "
            "and no RDS instance is named after it."
        )

    values = {
        RDS_TAG: [d["id"] for d in databases if not d["endpoint"] or d["endpoint"].endswith(RDS_ENDPOINT_SUFFIX)],
        ORACLE_TAG: [d["endpoint"] for d in databases if d["endpoint"]],
    }

    jobs = {
        name: partial(query_metric, template % {"scope": tag_filter(tag, values[tag])}, start, end)
        for name, tag, template in DATABASE_METRICS
        if values[tag]
    }
    found = _parallel(jobs)

    rows = []
    for db in databases:
        keys = {RDS_TAG: db["id"], ORACLE_TAG: db["endpoint"]}
        metrics = {
            name: _series_metric(found[name], tag, keys[tag]) for name, tag, _ in DATABASE_METRICS if name in found
        }
        rows.append({**db, "metrics": {k: v for k, v in metrics.items() if v}})

    return {"databases": rows}


def _error_count(query: str, start: int, end: int, interval: str) -> float:
    return sum(p["v"] for p in log_timeseries(query, start, end, interval))


SECTION_READERS: dict[str, Callable[[str, str, int, int, str], dict[str, Any]]] = {
    "monitors": _monitors_section,
    "logs": _logs_section,
    "traffic": _traffic_section,
    "servers": _servers_section,
    "database": _database_section,
    "events": _events_section,
}


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
