from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from ov.agent.integrations.datadog.connection import DatadogError, app_url, client, field
from ov.agent.integrations.datadog.hosts import hosts_in

MAX_LOG_LINES = 50
MAX_LOG_PAGE = 1000
MAX_EVENTS = 100
MONITORS_PAGE = 1000
MONITOR_GROUPS = 5
MESSAGE_CHARS = 400
LOG_MESSAGE_CHARS = 2000
DETAIL_CHARS = 300
TITLE_CHARS = 200
PATTERN_CHARS = 180
HEALTH_WORKERS = 8
TOP_PATTERNS = 8
SUMMARY_SAMPLES = 12
ISO_SECONDS_CHARS = 19
ISO_CLOCK = slice(11, 16)
EPOCH_MS_THRESHOLD = 10**11

MONITOR_ORDER = {"Alert": 0, "Warn": 1, "No Data": 2}
MONITOR_RANK = {"OK": 0, "No Data": 1, "Warn": 2, "Alert": 3}
QUIET_STATES = ("OK", "Ignored", "Skipped")

_RELATIVE = re.compile(r"^now(?:\s*-\s*(\d+)\s*([smhdw]))?$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_NOISE = (
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.I), "<hash>"),
    (re.compile(r"'[^']*'"), "'<v>'"),
    (re.compile(r'"[^"]*"'), '"<v>"'),
    (re.compile(r"\d+(?:[.:,]\d+)*"), "<n>"),
)


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


def _stamp_ms(stamp: str | int) -> int:
    if isinstance(stamp, str) and not stamp.isdigit():
        return to_ms(stamp, "now")
    return int(stamp)


def points_of(points: list[dict[str, Any]]) -> list[dict[str, float]]:
    return [{"t": _stamp_ms(field(p, "time")), "v": float(p.get("value") or 0)} for p in points]


def parallel(jobs: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=HEALTH_WORKERS) as pool:
        futures = {name: pool.submit(fn) for name, fn in jobs.items()}
        return {name: future.result() for name, future in futures.items()}


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

    return [_log_row(row) for row in field(data, "data")]


def _log_row(row: dict[str, Any]) -> dict[str, Any]:
    attrs = field(row, "attributes")
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

    return [_event_row(row) for row in field(data, "data")]


def _event_row(row: dict[str, Any]) -> dict[str, Any]:
    attrs = field(row, "attributes")
    inner = attrs.get("attributes") or {}

    return {
        "time": iso(attrs.get("timestamp") or inner.get("timestamp")),
        "title": str(inner.get("title") or attrs.get("title") or "")[:TITLE_CHARS],
        "message": str(attrs.get("message") or inner.get("message") or "")[:DETAIL_CHARS],
        "source": str(inner.get("source_type_name") or inner.get("source") or ""),
        "status": str(inner.get("status") or ""),
    }


def tag_filter(tag: str, values: list[str]) -> str:
    return f"{tag}:{values[0]}" if len(values) == 1 else f"{tag} IN ({','.join(values)})"


def metric_scope(scope: str, host_tag: str = "host") -> str:
    hosts = hosts_in(scope)
    if hosts:
        return tag_filter(host_tag, hosts)
    tags = [t for t in scope.split() if ":" in t and not t.startswith(("-", "("))]
    named = [f"{host_tag}:{t.removeprefix('host:')}" if t.startswith("host:") else t for t in tags]
    return ",".join(named) or "*"


def tag_of(series: dict[str, Any], tag: str) -> str | None:
    return next((p.split(":", 1)[1] for p in series["scope"].split(",") if p.startswith(f"{tag}:")), None)


def query_metric(query: str, start: int, end: int) -> list[dict[str, Any]]:
    params = {"from": start // 1000, "to": end // 1000, "query": query}
    with client() as dd:
        data = dd.call("GET", "/api/v1/query", "metrics", params=params)
    return [_metric_series(series, query) for series in field(data, "series")]


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
        "id": field(mon, "id"),
        "name": mon.get("name") or "",
        "state": str(mon.get("overall_state") or "Unknown"),
        "type": mon.get("type") or "",
        "groups": _monitor_groups(mon)[:MONITOR_GROUPS],
        "message": str(mon.get("message") or "")[:DETAIL_CHARS],
    }


def _site_pattern(site: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w.-]){re.escape(site.lower())}(?![\w-])")


def _names_a_tag(query: str, tags: set[str]) -> bool:
    text = query.lower()
    return any(re.search(rf"(?<![\w.-]){re.escape(t)}(?![\w.-])", text) for t in tags)


def instance_monitors(tags: list[str], site: str) -> list[dict[str, Any]]:
    params = {"group_states": "all", "page": 0, "page_size": MONITORS_PAGE}
    with client() as dd:
        data = dd.call("GET", "/api/v1/monitor", "monitors", params=params)

    wanted = {t.lower() for t in tags}
    named = _site_pattern(site)
    rows = []
    for mon in data:
        groups = (mon.get("state") or {}).get("groups") or {}
        mine = {k: str(v.get("status") or "OK") for k, v in groups.items() if wanted & set(k.lower().split(","))}
        if mine:
            state = max(mine.values(), key=lambda s: MONITOR_RANK.get(s, 0))
            firing = [k for k, v in mine.items() if v != "OK"]
            tag = next(iter(mine)).split(",")[0].split(":")[0]
            rows.append(
                {**_monitor_row(mon), "state": state, "groups": firing[:MONITOR_GROUPS], "watching": [len(mine), tag]}
            )
        elif named.search(str(mon.get("name") or "").lower()):
            rows.append({**_monitor_row(mon), "watching": [1, "site"]})
        elif _names_a_tag(str(mon.get("query") or ""), wanted):
            rows.append({**_monitor_row(mon), "watching": [1, "query"]})

    return sorted(rows, key=lambda m: (MONITOR_ORDER.get(m["state"], len(MONITOR_ORDER)), m["name"]))
