from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .. import credentials
from ..paths import agent_dir, write_atomic
from .ovproc import find_instance, host_of, instances

CREDENTIAL_KEY = "agent:datadog"
TIMEOUT_SECONDS = 30
MAX_LOG_LINES = 50
MESSAGE_CHARS = 400
HEALTH_TTL_SECONDS = 60

# Site id -> (API host, app host). The site is the domain users log in at.
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

# Read areas, the application key scope each needs, and a cheap call that proves access.
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

# Tests swap in a fake Datadog here.
TRANSPORT: httpx.BaseTransport | None = None

_lock = threading.Lock()
_health_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


class DatadogError(Exception):
    pass


def site_of(value: str) -> str:
    text = value.strip().lower()
    if not text:
        return DEFAULT_SITE
    host = urlsplit(text if "://" in text else f"https://{text}").hostname or text
    for site, (api, app) in SITES.items():
        if host in (site, api, app):
            return site
    # Longest first, so us5.datadoghq.com is not taken for datadoghq.com.
    for site in sorted(SITES, key=len, reverse=True):
        if host.endswith("." + site):
            return site
    raise DatadogError(f"Unknown Datadog site: {value}")


def app_url(site: str) -> str:
    return f"https://{SITES[site][1]}"


# Non-secret state; the keys themselves live in the OS keyring.
def _state_file():
    return agent_dir() / "datadog.json"


def load_state() -> dict[str, Any]:
    path = _state_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict[str, Any]) -> None:
    with _lock:
        write_atomic(_state_file(), json.dumps(state, indent=2))


def _keys() -> tuple[str, str] | None:
    secrets = credentials.get(CREDENTIAL_KEY) or {}
    api, app = secrets.get("api_key"), secrets.get("app_key")
    return (str(api), str(app)) if api and app else None


def connected() -> bool:
    return bool(load_state().get("site")) and _keys() is not None


def permissions() -> dict[str, bool]:
    stored = load_state().get("permissions") or {}
    return {area: bool(stored.get(area)) for area in AREAS}


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

    def call(self, method: str, path: str, area: str = "", **kwargs: Any) -> Any:
        for attempt in range(2):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                raise DatadogError(f"Could not reach Datadog: {exc}") from None
            # Rate limited: wait what Datadog asks, once, then give up with a clear message.
            if response.status_code == 429 and attempt == 0:
                wait = response.headers.get("X-RateLimit-Reset", "2")
                time.sleep(min(float(wait) if wait.replace(".", "").isdigit() else 2, 10))
                continue
            break
        if response.status_code < 400:
            return response.json() if response.content else {}
        raise DatadogError(_explain(response, area))


def _explain(response: httpx.Response, area: str) -> str:
    try:
        errors = response.json().get("errors") or []
    except ValueError:
        errors = []
    detail = "; ".join(e if isinstance(e, str) else e.get("detail", str(e)) for e in errors)
    if response.status_code == 401:
        return "Datadog rejected the API key (wrong key, or a key for another site)."
    if response.status_code == 403:
        scope = AREAS.get(area)
        need = f" It needs the {scope} scope." if scope else ""
        return f"Datadog refused this request: the application key may not allow it.{need}"
    if response.status_code == 429:
        return "Datadog rate limit reached. Try again in a minute."
    return f"Datadog returned {response.status_code}: {detail or response.text[:200]}"


def client() -> Client:
    state = load_state()
    keys = _keys()
    if not state.get("site") or keys is None:
        raise DatadogError("Datadog is not connected. Connect it in Settings > Integrations.")
    return Client(state["site"], *keys)


def _probe(dd: Client, area: str) -> bool:
    now = int(time.time())
    try:
        if area == "logs":
            dd.call(
                "POST",
                "/api/v2/logs/events/search",
                area,
                json={
                    "filter": {"from": "now-15m", "to": "now", "query": "*"},
                    "page": {"limit": 1},
                },
            )
        elif area == "metrics":
            dd.call(
                "GET",
                "/api/v1/query",
                area,
                params={"from": now - 300, "to": now, "query": "avg:system.load.1{*}"},
            )
        elif area == "monitors":
            dd.call("GET", "/api/v1/monitor", area, params={"page": 0, "page_size": 1})
        elif area == "events":
            dd.call(
                "GET",
                "/api/v2/events",
                area,
                params={"filter[from]": "now-1h", "filter[to]": "now", "page[limit]": 1},
            )
        elif area == "apm":
            dd.call(
                "POST",
                "/api/v2/spans/events/search",
                area,
                json=_spans_body("*", "now-15m", "now", 1),
            )
        elif area == "hosts":
            dd.call("GET", "/api/v1/hosts", area, params={"count": 1})
    except DatadogError:
        return False
    return True


def check(site: str, api_key: str, app_key: str) -> dict[str, Any]:
    api_key, app_key = api_key.strip(), app_key.strip()
    if not api_key or not app_key:
        raise DatadogError("Both the API key and the application key are needed.")
    with Client(site, api_key, app_key) as dd:
        try:
            valid = dd.call("GET", "/api/v1/validate").get("valid")
        except DatadogError:
            raise DatadogError(
                "Datadog rejected the API key. Check that it is copied whole and that the site "
                "matches where you log in to Datadog."
            ) from None
        if not valid:
            raise DatadogError("Datadog says the API key is not valid for this site.")
        with ThreadPoolExecutor(max_workers=len(AREAS)) as pool:
            found = dict(zip(AREAS, pool.map(lambda a: _probe(dd, a), AREAS), strict=True))
    if not any(found.values()):
        raise DatadogError(
            "The API key works, but the application key cannot read anything. Check that it is "
            "copied whole and has read scopes such as logs_read_data and monitors_read."
        )
    return found


def connect(site: str, api_key: str, app_key: str) -> dict[str, Any]:
    site = site_of(site)
    found = check(site, api_key, app_key)
    credentials.put(CREDENTIAL_KEY, {"api_key": api_key.strip(), "app_key": app_key.strip()})
    state = load_state()
    state.update(
        {
            "site": site,
            "apiKeyLast4": api_key.strip()[-4:],
            "appKeyLast4": app_key.strip()[-4:],
            "permissions": found,
            "checkedAt": int(time.time() * 1000),
            "error": None,
        }
    )
    _save_state(state)
    _health_cache.clear()
    return status()


def retest() -> dict[str, Any]:
    state = load_state()
    keys = _keys()
    if not state.get("site") or keys is None:
        raise DatadogError("Datadog is not connected.")
    try:
        state["permissions"] = check(state["site"], *keys)
        state["error"] = None
    except DatadogError as exc:
        state["error"] = str(exc)
    state["checkedAt"] = int(time.time() * 1000)
    _save_state(state)
    _health_cache.clear()
    return status()


def disconnect() -> dict[str, Any]:
    credentials.delete(CREDENTIAL_KEY)
    state = load_state()
    _save_state({"matches": state.get("matches") or {}})
    _health_cache.clear()
    return status()


def status() -> dict[str, Any]:
    state = load_state()
    on = connected()
    site = state.get("site") or DEFAULT_SITE
    return {
        "connected": on,
        "site": site,
        "appUrl": app_url(site),
        "apiKeyLast4": state.get("apiKeyLast4") if on else None,
        "appKeyLast4": state.get("appKeyLast4") if on else None,
        "permissions": permissions() if on else {a: False for a in AREAS},
        "checkedAt": state.get("checkedAt") if on else None,
        "error": state.get("error") if on else None,
        "matches": state.get("matches") or {},
        "sites": [{"id": s, "app": SITES[s][1]} for s in SITES],
        "scopes": SCOPES,
    }


# Instance matching: each OneVizion instance maps to a Datadog filter such as "host:acme*".
def save_matches(matches: dict[str, str]) -> dict[str, Any]:
    state = load_state()
    cleaned = {k: v.strip() for k, v in matches.items() if isinstance(v, str)}
    state["matches"] = {k: v for k, v in cleaned.items() if v}
    _save_state(state)
    _health_cache.clear()
    return status()


def filter_for(alias: str) -> str:
    matches = load_state().get("matches") or {}
    if matches.get(alias):
        return matches[alias]
    found = find_instance(alias)
    if found is None:
        return ""
    # A tenant shares its host's servers unless it has its own match.
    same_host = [i for i in instances() if i["host"] == found["host"] and matches.get(i["alias"])]
    same_host.sort(key=lambda i: bool(i["tenant"]))
    return matches[same_host[0]["alias"]] if same_host else ""


def _label(host: str) -> str:
    return host.split(":")[0].split(".")[0].lower()


def _tokens(value: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if t}


def _bucket_counts(dd: Client, facet: str) -> list[tuple[str, int]]:
    data = dd.call(
        "POST",
        "/api/v2/logs/analytics/aggregate",
        "logs",
        json={
            "compute": [{"aggregation": "count", "type": "total"}],
            "filter": {"from": "now-24h", "to": "now", "query": "*"},
            "group_by": [{"facet": facet, "limit": 500}],
        },
    )
    out = []
    for bucket in (data.get("data") or {}).get("buckets") or []:
        value = (bucket.get("by") or {}).get(facet)
        count = (bucket.get("computes") or {}).get("c0") or 0
        if value:
            out.append((str(value), int(count)))
    return out


def discover() -> dict[str, Any]:
    with client() as dd:
        if not permissions().get("logs"):
            raise DatadogError("Matching needs log access (logs_read_data) to see what exists.")
        with ThreadPoolExecutor(max_workers=2) as pool:
            hosts, services = pool.map(lambda f: _bucket_counts(dd, f), ["host", "service"])

    values = [{"kind": "host", "value": v, "count": c} for v, c in hosts] + [
        {"kind": "service", "value": v, "count": c} for v, c in services
    ]
    values.sort(key=lambda v: -v["count"])
    suggestions = []
    for inst in instances():
        if inst["tenant"]:
            continue
        suggestions.append({"alias": inst["alias"], **_suggest(inst["host"], hosts, services)})
    return {"values": values[:400], "suggestions": suggestions}


def _suggest(host: str, hosts: list[tuple[str, int]], services: list[tuple[str, int]]) -> dict:
    bare = host.split(":")[0].lower()
    label = _label(host)
    for value, count in hosts:
        if value.lower() == bare:
            return {"filter": f"host:{value}", "count": count, "why": "Host name matches"}
    for kind, rows in (("service", services), ("host", hosts)):
        exact = [(v, c) for v, c in rows if v.lower() in (label, bare)]
        if exact:
            return {"filter": f"{kind}:{exact[0][0]}", "count": exact[0][1], "why": f"{kind} name"}
    related = [(v, c) for v, c in hosts if label in _tokens(v) or v.lower().startswith(label)]
    if related:
        prefix = _common_prefix([v for v, _ in related])
        total = sum(c for _, c in related)
        if len(related) > 1 and len(prefix) >= len(label):
            return {"filter": f"host:{prefix}*", "count": total, "why": f"{len(related)} hosts"}
        best = max(related, key=lambda r: r[1])
        return {"filter": f"host:{best[0]}", "count": best[1], "why": "Host name contains it"}
    related = [(v, c) for v, c in services if label in _tokens(v)]
    if related:
        best = max(related, key=lambda r: r[1])
        return {"filter": f"service:{best[0]}", "count": best[1], "why": "Service contains it"}
    return {"filter": "", "count": 0, "why": "No match found"}


def _common_prefix(values: list[str]) -> str:
    first, last = min(values), max(values)
    size = 0
    while size < min(len(first), len(last)) and first[size] == last[size]:
        size += 1
    return first[:size]


def count_logs(query: str) -> int:
    with client() as dd:
        data = dd.call(
            "POST",
            "/api/v2/logs/analytics/aggregate",
            "logs",
            json={
                "compute": [{"aggregation": "count", "type": "total"}],
                "filter": {"from": "now-24h", "to": "now", "query": query or "*"},
            },
        )
    buckets = (data.get("data") or {}).get("buckets") or []
    return int((buckets[0].get("computes") or {}).get("c0") or 0) if buckets else 0


# Time windows accept "now", "now-2h", ISO dates or epoch values; Datadog wants epoch ms.
_RELATIVE = re.compile(r"^now(?:\s*-\s*(\d+)\s*([smhdw]))?$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def to_ms(value: Any, default: str) -> int:
    text = str(value or default).strip().lower()
    match = _RELATIVE.match(text)
    if match:
        back = int(match.group(1) or 0) * _UNITS[match.group(2) or "s"]
        return int((time.time() - back) * 1000)
    if text.isdigit():
        number = int(text)
        return number if number > 10**11 else number * 1000
    try:
        parsed = datetime.fromisoformat(text.replace("z", "+00:00"))
    except ValueError:
        raise DatadogError(f'Not a time: "{value}". Use now-2h, an ISO date, or epoch.') from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def iso(ms: int | float | str | None) -> str:
    if ms is None or ms == "":
        return ""
    if isinstance(ms, str) and not ms.replace(".", "").isdigit():
        return ms[:19].replace("T", " ")
    seconds = float(ms) / (1000 if float(ms) > 10**11 else 1)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def combine(scope: str, query: str) -> str:
    parts = [p for p in (scope.strip(), query.strip()) if p]
    if len(parts) == 2:
        return f"({parts[0]}) {parts[1]}"
    return parts[0] if parts else "*"


def logs_link(site: str, query: str, start: int, end: int) -> str:
    return f"{app_url(site)}/logs?query={quote(query)}&from_ts={start}&to_ts={end}&live=false"


def search_logs(query: str, start: int, end: int, limit: int) -> list[dict[str, Any]]:
    with client() as dd:
        data = dd.call(
            "POST",
            "/api/v2/logs/events/search",
            "logs",
            json={
                "filter": {"from": str(start), "to": str(end), "query": query or "*"},
                "page": {"limit": max(1, min(limit, 1000))},
                "sort": "-timestamp",
            },
        )
    out = []
    for row in data.get("data") or []:
        attrs = row.get("attributes") or {}
        inner = attrs.get("attributes") or {}
        error = inner.get("error") if isinstance(inner.get("error"), dict) else {}
        out.append(
            {
                "time": iso(attrs.get("timestamp")),
                "host": attrs.get("host") or "",
                "service": attrs.get("service") or "",
                "status": attrs.get("status") or "",
                "message": str(attrs.get("message") or error.get("message") or "")[:2000],
                "errorKind": str(error.get("kind") or ""),
            }
        )
    return out


# Groups messages that differ only in ids, numbers, quoted values and hashes.
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
    return re.sub(r"\s+", " ", text)[:180]


def top_patterns(rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    sample: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = pattern_of(
            row["errorKind"] + " " + row["message"] if row["errorKind"] else row["message"]
        )
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
    with client() as dd:
        data = dd.call(
            "POST",
            "/api/v2/logs/analytics/aggregate",
            "logs",
            json={
                "compute": [{"aggregation": "count", "type": "timeseries", "interval": interval}],
                "filter": {"from": str(start), "to": str(end), "query": query or "*"},
            },
        )
    buckets = (data.get("data") or {}).get("buckets") or []
    points = (buckets[0].get("computes") or {}).get("c0") if buckets else []
    out = []
    for point in points or []:
        stamp = point.get("time")
        ms = (
            to_ms(stamp, "now")
            if isinstance(stamp, str) and not stamp.isdigit()
            else int(stamp or 0)
        )
        out.append({"t": ms, "v": float(point.get("value") or 0)})
    return out


def metric_scope(scope: str) -> str:
    tags = [t for t in scope.split() if ":" in t and not t.startswith(("-", "("))]
    return ",".join(tags) or "*"


def query_metric(query: str, start: int, end: int) -> list[dict[str, Any]]:
    with client() as dd:
        data = dd.call(
            "GET",
            "/api/v1/query",
            "metrics",
            params={"from": start // 1000, "to": end // 1000, "query": query},
        )
    out = []
    for series in data.get("series") or []:
        points = [
            {"t": int(p[0]), "v": float(p[1])}
            for p in series.get("pointlist") or []
            if p and len(p) > 1 and p[1] is not None
        ]
        out.append(
            {
                "name": series.get("expression") or series.get("metric") or query,
                "scope": series.get("scope") or "",
                "unit": ((series.get("unit") or [{}])[0] or {}).get("short_name") or "",
                "points": points,
            }
        )
    return out


def summarize_series(series: dict[str, Any], samples: int = 12) -> str:
    values = [p["v"] for p in series["points"]]
    if not values:
        return f"{series['name']} [{series['scope']}]: no data"
    step = max(1, len(series["points"]) // samples)
    sampled = ", ".join(
        f"{iso(p['t'])[11:16]}={_num(p['v'])}" for p in series["points"][::step][:samples]
    )
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


# Monitors are not filterable by an arbitrary log query, so match the filter's tag values
# against each monitor's query, tags and alerting groups.
def monitors_for(scope: str, include_ok: bool) -> list[dict[str, Any]]:
    with client() as dd:
        data = dd.call(
            "GET",
            "/api/v1/monitor",
            "monitors",
            params={"group_states": "alert,warn,no data", "page": 0, "page_size": 1000},
        )
    needles = [t.split(":", 1)[1].rstrip("*").lower() for t in scope.split() if ":" in t]
    needles = [n for n in needles if n]
    out = []
    for mon in data if isinstance(data, list) else []:
        groups = ((mon.get("state") or {}).get("groups") or {}).keys()
        haystack = " ".join([str(mon.get("query", "")), " ".join(mon.get("tags") or []), *groups])
        if needles and not any(n in haystack.lower() for n in needles):
            continue
        state = str(mon.get("overall_state") or "Unknown")
        if not include_ok and state in ("OK", "Ignored", "Skipped"):
            continue
        out.append(
            {
                "id": mon.get("id"),
                "name": mon.get("name") or "",
                "state": state,
                "type": mon.get("type") or "",
                "groups": [g for g in groups][:5],
                "message": str(mon.get("message") or "")[:300],
            }
        )
    order = {"Alert": 0, "Warn": 1, "No Data": 2}
    return sorted(out, key=lambda m: (order.get(m["state"], 3), m["name"]))


def events_for(query: str, start: int, end: int, limit: int) -> list[dict[str, Any]]:
    with client() as dd:
        data = dd.call(
            "GET",
            "/api/v2/events",
            "events",
            params={
                "filter[query]": query or "*",
                "filter[from]": str(start),
                "filter[to]": str(end),
                "page[limit]": max(1, min(limit, 100)),
                "sort": "-timestamp",
            },
        )
    out = []
    for row in data.get("data") or []:
        attrs = row.get("attributes") or {}
        inner = attrs.get("attributes") or {}
        out.append(
            {
                "time": iso(attrs.get("timestamp") or inner.get("timestamp")),
                "title": str(inner.get("title") or attrs.get("title") or "")[:200],
                "message": str(attrs.get("message") or inner.get("message") or "")[:300],
                "source": str(inner.get("source_type_name") or inner.get("source") or ""),
                "status": str(inner.get("status") or ""),
            }
        )
    return out


def _spans_body(query: str, start: str, end: str, limit: int) -> dict[str, Any]:
    return {
        "data": {
            "type": "search_request",
            "attributes": {
                "filter": {"from": start, "to": end, "query": query or "*"},
                "page": {"limit": limit},
                "sort": "-timestamp",
            },
        }
    }


def slow_endpoints(query: str, start: int, end: int, limit: int = 10) -> list[dict[str, Any]]:
    with client() as dd:
        data = dd.call(
            "POST",
            "/api/v2/spans/analytics/aggregate",
            "apm",
            json={
                "data": {
                    "type": "aggregate_request",
                    "attributes": {
                        "compute": [
                            {"aggregation": "pc95", "metric": "@duration", "type": "total"},
                            {"aggregation": "count", "type": "total"},
                        ],
                        "filter": {"from": str(start), "to": str(end), "query": query or "*"},
                        "group_by": [
                            {
                                "facet": "resource_name",
                                "limit": limit,
                                "sort": {
                                    "aggregation": "pc95",
                                    "metric": "@duration",
                                    "order": "desc",
                                    "type": "measure",
                                },
                            }
                        ],
                    },
                }
            },
        )
    out = []
    for bucket in data.get("data") or []:
        attrs = bucket.get("attributes") or bucket
        compute = attrs.get("compute") or attrs.get("computes") or {}
        out.append(
            {
                "resource": str((attrs.get("by") or {}).get("resource_name") or "?"),
                "p95Ms": round(float(compute.get("c0") or 0) / 1e6, 1),
                "count": int(compute.get("c1") or 0),
            }
        )
    return out


def error_spans(query: str, start: int, end: int, limit: int) -> list[dict[str, Any]]:
    with client() as dd:
        data = dd.call(
            "POST",
            "/api/v2/spans/events/search",
            "apm",
            json=_spans_body(combine(query, "status:error"), str(start), str(end), limit),
        )
    out = []
    for row in data.get("data") or []:
        attrs = row.get("attributes") or {}
        custom = attrs.get("custom") or attrs.get("attributes") or {}
        error = custom.get("error") if isinstance(custom.get("error"), dict) else {}
        out.append(
            {
                "time": iso(attrs.get("start_timestamp") or attrs.get("timestamp")),
                "service": attrs.get("service") or "",
                "resource": attrs.get("resource_name") or "",
                "error": str(error.get("message") or error.get("type") or "")[:300],
                "trace": attrs.get("trace_id") or "",
            }
        )
    return out


# Health page: one report per instance and range, cached briefly to stay inside rate limits.
RANGES = {"1h": (3600, "1m"), "24h": (86400, "30m"), "7d": (604800, "6h")}
METRICS = [
    ("cpu", "CPU", "avg:system.cpu.user{%s}", "%"),
    ("load", "Load (per core)", "avg:system.load.norm.1{%s}", ""),
    ("memory", "Memory usable", "avg:system.mem.pct_usable{%s}*100", "%"),
    ("disk", "Disk in use", "max:system.disk.in_use{%s}*100", "%"),
    ("heap", "JVM heap", "avg:jvm.heap_memory{%s}", "B"),
]


def health(alias: str, range_key: str, ov_side: Any = None) -> dict[str, Any]:
    if range_key not in RANGES:
        range_key = "24h"
    key = (alias, range_key)
    cached = _health_cache.get(key)
    if cached and time.time() - cached[0] < HEALTH_TTL_SECONDS:
        return cached[1]

    state = load_state()
    scope = filter_for(alias)
    seconds, interval = RANGES[range_key]
    end = int(time.time() * 1000)
    start = end - seconds * 1000
    allowed = permissions()
    site = state.get("site") or DEFAULT_SITE
    report: dict[str, Any] = {
        "instance": alias,
        "range": range_key,
        "scope": scope,
        "from": start,
        "to": end,
        "appUrl": app_url(site),
        "links": {
            "logs": logs_link(site, combine(scope, "status:error"), start, end),
            "monitors": f"{app_url(site)}/monitors/manage",
            "apm": f"{app_url(site)}/apm/traces?query={quote(scope)}",
            "events": f"{app_url(site)}/event/explorer?query={quote(scope)}",
        },
        "errors": {},
    }
    if not scope:
        report["errors"]["scope"] = "This instance is not matched to Datadog yet."
        return report

    errors_query = combine(scope, "status:error")

    def run(name: str, fn: Any) -> None:
        try:
            report[name] = fn()
        except Exception as exc:
            report["errors"][name] = str(exc)

    jobs: list[tuple[str, Any]] = []
    if allowed["monitors"]:
        jobs.append(("monitors", lambda: monitors_for(scope, include_ok=True)))
    if allowed["logs"]:
        jobs += [
            ("errorSeries", lambda: log_timeseries(errors_query, start, end, interval)),
            ("logSeries", lambda: log_timeseries(scope, start, end, interval)),
            (
                "previousErrors",
                lambda: sum(
                    p["v"]
                    for p in log_timeseries(errors_query, start - seconds * 1000, start, interval)
                ),
            ),
            ("topErrors", lambda: top_patterns(search_logs(errors_query, start, end, 300))),
        ]
    if allowed["events"]:
        jobs.append(("events", lambda: events_for(scope, start, end, 15)))
    if allowed["apm"]:
        jobs.append(("slowEndpoints", lambda: slow_endpoints(scope, start, end, 8)))
    if allowed["metrics"]:
        tags = metric_scope(scope)
        for name, title, template, unit in METRICS:
            jobs.append(
                (
                    f"metric:{name}",
                    lambda t=template, n=title, u=unit: _metric_card(n, t % tags, u, start, end),
                )
            )
    if ov_side is not None:
        jobs.append(("onevizion", ov_side))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda job: run(*job), jobs))

    report["metrics"] = [
        report.pop(name) for name in [k for k in list(report) if k.startswith("metric:")]
    ]
    report["metrics"] = [m for m in report["metrics"] if m and m["points"]]
    for name in [k for k in list(report["errors"]) if k.startswith("metric:")]:
        report["errors"].pop(name)
    _health_cache[key] = (time.time(), report)
    return report


def _metric_card(title: str, query: str, unit: str, start: int, end: int) -> dict | None:
    series = query_metric(query, start, end)
    points: dict[int, list[float]] = {}
    for s in series:
        for p in s["points"]:
            points.setdefault(p["t"], []).append(p["v"])
    merged = [{"t": t, "v": sum(v) / len(v)} for t, v in sorted(points.items())]
    if not merged:
        return None
    return {"title": title, "query": query, "unit": unit, "points": merged, "hosts": len(series)}


def resolve_scope(instance: str | None, fallback: str) -> tuple[str, str]:
    target = (instance or fallback or "").strip()
    if not target:
        return "", ""
    found = find_instance(target)
    alias = found["alias"] if found else ""
    scope = filter_for(alias) if alias else ""
    if found and not scope:
        raise DatadogError(
            f"{found['host']} is not matched to Datadog yet. Match it in Settings > "
            "Integrations > Datadog, or pass a query with its host or service tag."
        )
    return alias or host_of(target), scope
