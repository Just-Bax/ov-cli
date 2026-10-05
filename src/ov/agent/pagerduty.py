from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .. import credentials
from ..paths import agent_dir, write_atomic
from . import datadog
from .ovproc import find_instance, instances

CREDENTIAL_KEY = "agent:pagerduty"
TIMEOUT_SECONDS = 30
RATE_LIMIT_WAIT_SECONDS = 2
PAGE_SIZE = 100
MAX_INCIDENTS = 50
INCIDENTS_LIMIT = 1000
SERVICES_LIMIT = 2000
ONCALLS_LIMIT = 200
LOG_ENTRIES_LIMIT = 100
ALERTS_LIMIT = 25
TEXT_CHARS = 600
DETAIL_CHARS = 300
DESCRIPTION_CHARS = 200
ERROR_BODY_CHARS = 200
SERVICES_TTL_SECONDS = 600
HEALTH_TTL_SECONDS = 60
OPEN_LOOKBACK_DAYS = 30
DAY_MS = 86_400_000
ONCALL_WINDOW_MS = 60_000

REGIONS = {"us": "https://api.pagerduty.com", "eu": "https://api.eu.pagerduty.com"}
DEFAULT_REGION = "us"
NON_ACCOUNT_SUBDOMAINS = ("app", "www", "eu", "api")
AREAS = ("incidents", "services", "oncall")
PROBE_PATHS = {"incidents": "/incidents", "services": "/services", "oncall": "/oncalls"}
OPEN_STATUSES = ["triggered", "acknowledged"]
STATUS_MESSAGES = {
    401: "PagerDuty rejected the API key (wrong key, or a key for the other region).",
    404: "PagerDuty has no such incident or object.",
    429: "PagerDuty rate limit reached. Try again in a minute.",
}

TRANSPORT: httpx.BaseTransport | None = None

_lock = threading.Lock()
_services_cache: tuple[float, list[dict[str, Any]]] | None = None
_health_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


class PagerDutyError(Exception):
    pass


def account_of(value: str) -> tuple[str, str]:
    text = value.strip().lower()
    if not text:
        return "", DEFAULT_REGION

    host = urlsplit(text if "://" in text else f"https://{text}").hostname
    if host and host.endswith("pagerduty.com"):
        region = "eu" if host.endswith(".eu.pagerduty.com") else DEFAULT_REGION
        sub = host.split(".")[0]
        return ("" if sub in NON_ACCOUNT_SUBDOMAINS else sub), region

    if host and re.fullmatch(r"[a-z0-9-]+", host):
        return host, DEFAULT_REGION

    raise PagerDutyError(f"Not a PagerDuty address: {value}")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _state_file() -> Path:
    return agent_dir() / "pagerduty.json"


def load_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PagerDutyError(f"Cannot read the PagerDuty settings in {path}: {exc}") from None
    if isinstance(data, dict):
        return data

    raise PagerDutyError(f"The PagerDuty settings in {path} are not a JSON object.")


def _save_state(state: dict[str, Any]) -> None:
    with _lock:
        write_atomic(_state_file(), json.dumps(state, indent=2))


def _stored(state: dict[str, Any], key: str) -> Any:
    if key not in state:
        raise PagerDutyError(f"The PagerDuty settings have no {key}. Reconnect PagerDuty in Settings > Integrations.")
    return state[key]


def _field(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise PagerDutyError(f"PagerDuty returned a response without {key}.")
    return data[key]


def _key() -> str | None:
    secrets = credentials.get(CREDENTIAL_KEY)
    if secrets is None:
        return None

    if not secrets.get("api_key"):
        raise PagerDutyError("The stored PagerDuty key is empty. Reconnect PagerDuty in Settings > Integrations.")
    return str(secrets["api_key"])


def connected() -> bool:
    return "region" in load_state() and _key() is not None


def permissions() -> dict[str, bool]:
    state = load_state()
    if "region" not in state:
        return dict.fromkeys(AREAS, False)

    stored = _stored(state, "permissions")
    return {area: bool(stored[area]) for area in AREAS}


def web_url(state: dict[str, Any]) -> str:
    sub = state.get("subdomain", "")
    eu = ".eu" if state.get("region") == "eu" else ""
    return f"https://{sub}{eu}.pagerduty.com" if sub else f"https://app{eu}.pagerduty.com"


class Client:
    def __init__(self, region: str, api_key: str) -> None:
        self._http = httpx.Client(
            base_url=REGIONS[region],
            headers={
                "Authorization": f"Token token={api_key}",
                "Accept": "application/vnd.pagerduty+json;version=2",
            },
            timeout=TIMEOUT_SECONDS,
            transport=TRANSPORT,
        )

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: Any) -> None:
        self._http.close()

    def _send(self, path: str, params: dict[str, Any]) -> httpx.Response:
        try:
            return self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise PagerDutyError(f"Could not reach PagerDuty: {exc}") from None

    def get(self, path: str, area: str = "", **params: Any) -> dict[str, Any]:
        response = self._send(path, params)
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            time.sleep(RATE_LIMIT_WAIT_SECONDS)
            response = self._send(path, params)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise PagerDutyError(_explain(response, area))
        return response.json() if response.content else {}

    def pages(self, path: str, key: str, area: str, limit: int, **params: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while len(out) < limit:
            data = self.get(path, area, limit=min(PAGE_SIZE, limit - len(out)), offset=len(out), **params)
            rows = _field(data, key)
            out += rows
            if not _field(data, "more") or not rows:
                break
        return out


def _explain(response: httpx.Response, area: str) -> str:
    code = response.status_code
    if code in STATUS_MESSAGES:
        return STATUS_MESSAGES[code]

    if code == httpx.codes.FORBIDDEN:
        what = f" ({area})" if area else ""
        return f"PagerDuty refused this request{what}: your user cannot read it."

    return f"PagerDuty returned {code}: {_error_detail(response)}"


def _error_detail(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return response.text[:ERROR_BODY_CHARS]

    detail = "; ".join([str(error.get("message") or ""), *map(str, error.get("errors") or [])])
    return detail.strip("; ") or response.text[:ERROR_BODY_CHARS]


def client() -> Client:
    state = load_state()
    key = _key()
    if "region" not in state or key is None:
        raise PagerDutyError("PagerDuty is not connected. Connect it in Settings > Integrations.")
    return Client(state["region"], key)


def _probe(pd: Client, area: str) -> bool:
    try:
        pd.get(PROBE_PATHS[area], area, limit=1)
    except PagerDutyError:
        return False
    return True


def check(region: str, api_key: str) -> tuple[dict[str, Any], dict[str, bool]]:
    api_key = api_key.strip()
    if not api_key:
        raise PagerDutyError("Paste your API user token.")

    with Client(region, api_key) as pd:
        try:
            me = _field(pd.get("/users/me"), "user")
        except PagerDutyError as exc:
            raise PagerDutyError(f"{exc} Use a User API token from My Profile > User Settings.") from None
        with ThreadPoolExecutor(max_workers=len(AREAS)) as pool:
            found = dict(zip(AREAS, pool.map(lambda a: _probe(pd, a), AREAS), strict=True))
    return me, found


def connect(account: str, api_key: str) -> dict[str, Any]:
    sub, region = account_of(account)
    api_key = api_key.strip()
    me, found = check(region, api_key)
    credentials.put(CREDENTIAL_KEY, {"api_key": api_key})
    if not sub:
        sub = account_of(_field(me, "html_url"))[0]

    state = load_state()
    state.update(
        {
            "region": region,
            "subdomain": sub,
            "user": _field(me, "name"),
            "email": me.get("email") or "",
            "keyLast4": api_key[-4:],
            "permissions": found,
            "checkedAt": _now_ms(),
            "error": None,
        }
    )
    _save_state(state)
    _forget_caches()
    return status()


def retest() -> dict[str, Any]:
    state = load_state()
    key = _key()
    if "region" not in state or key is None:
        raise PagerDutyError("PagerDuty is not connected. Connect it in Settings > Integrations.")

    try:
        _, state["permissions"] = check(state["region"], key)
        state["error"] = None
    except PagerDutyError as exc:
        state["error"] = str(exc)
    state["checkedAt"] = _now_ms()
    _save_state(state)
    _forget_caches()
    return status()


def disconnect() -> dict[str, Any]:
    credentials.delete(CREDENTIAL_KEY)
    state = load_state()
    _save_state({"subdomain": state["subdomain"]} if "subdomain" in state else {})
    _forget_caches()
    return status()


def _forget_caches() -> None:
    global _services_cache
    _services_cache = None
    _health_cache.clear()


def status() -> dict[str, Any]:
    state = load_state()
    on = connected()
    private = ("user", "email", "keyLast4", "checkedAt", "error")
    details = {key: _stored(state, key) for key in private} if on else dict.fromkeys(private)

    return {
        "connected": on,
        "region": state.get("region", DEFAULT_REGION),
        "subdomain": state.get("subdomain", ""),
        "webUrl": web_url(state),
        **details,
        "permissions": permissions() if on else dict.fromkeys(AREAS, False),
    }


def services(refresh: bool = False) -> list[dict[str, Any]]:
    global _services_cache
    if _services_cache and not refresh and time.time() - _services_cache[0] < SERVICES_TTL_SECONDS:
        return _services_cache[1]

    with client() as pd:
        rows = pd.pages("/services", "services", "services", SERVICES_LIMIT)
    out = [
        {
            "id": _field(s, "id"),
            "name": s.get("name") or s.get("summary") or "",
            "description": str(s.get("description") or "")[:DESCRIPTION_CHARS],
            "status": s.get("status") or "",
            "policy": (s.get("escalation_policy") or {}).get("id") or "",
            "url": s.get("html_url") or "",
        }
        for s in rows
    ]
    out.sort(key=lambda s: s["name"].lower())
    _services_cache = (time.time(), out)
    return out


_HOST = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+\b")
_TAG = re.compile(r"\[([a-z0-9][a-z0-9 _-]*)\]")
_PAIR = re.compile(r"\b[a-z_]+:([a-z0-9][a-z0-9_-]*)")
WEBSITE_KEYS = ("website", "host", "hostname", "url", "client_url")
EMPTY = {"", "none", "null", "n/a", "na", "-", "unknown"}


def _instance_of(alias: str) -> dict[str, Any]:
    found = find_instance(alias)
    if found is None:
        raise PagerDutyError(f"No signed-in instance matches {alias}.")
    return found


def main_alias(alias: str) -> str:
    found = _instance_of(alias)
    same_host = [i for i in instances() if i["host"] == found["host"]]
    return min(same_host, key=lambda i: bool(i["tenant"]))["alias"]


def _channel(row: dict[str, Any]) -> dict[str, Any]:
    return (row.get("first_trigger_log_entry") or {}).get("channel") or {}


def _details(row: dict[str, Any]) -> dict[str, Any]:
    details = _channel(row).get("details")
    return details if isinstance(details, dict) else {}


def _hostname(value: str) -> str:
    return urlsplit(value if "://" in value else f"//{value}").hostname or value


def websites_of(row: dict[str, Any]) -> list[str]:
    details = _details(row)
    values = [str(details.get(key) or "").strip().lower() for key in WEBSITE_KEYS]
    hosts = [_hostname(v) for v in values if v not in EMPTY]
    return [h for h in dict.fromkeys(hosts) if h not in EMPTY]


def database_of(row: dict[str, Any]) -> str:
    value = str(_details(row).get("database") or "").strip().lower()
    return "" if value in EMPTY else value


def forget_host(host: str) -> None:
    state = load_state()
    databases = state.get("databases", {})
    if _host_key(host) not in databases:
        return

    del databases[_host_key(host)]
    _save_state(state)


def learn_databases(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    state = load_state()
    known: dict[str, list[str]] = {k: list(v) for k, v in state.get("databases", {}).items()}
    pairs = [(site, r["database"]) for r in rows if r["database"] for site in r["websites"]]
    new = [(site, db) for site, db in dict.fromkeys(pairs) if db not in known.get(site, [])]
    if not new:
        return known

    for site, db in new:
        known.setdefault(site, []).append(db)
    state["databases"] = known
    _save_state(state)
    return known


def _text_of(row: dict[str, Any]) -> str:
    channel = _channel(row)
    parts = [row.get("title"), row.get("summary"), channel.get("summary"), channel.get("details")]
    return " ".join(json.dumps(p) if isinstance(p, dict) else str(p or "") for p in parts).lower()


def _datadog_hosts(alias: str) -> list[tuple[str, bool]]:
    scope = datadog.filter_for(alias)
    grouped = datadog.hosts_in(scope)
    if grouped is not None:
        return [(host.lower(), False) for host in grouped]

    tags = [tag.partition(":") for tag in scope.split()]
    return [(value.lower().rstrip("*"), value.endswith("*")) for name, _, value in tags if name == "host" and value]


def _named_by_datadog(hosts: set[str], alias: str) -> bool:
    return any(h == value or (prefix and h.startswith(value)) for value, prefix in _datadog_hosts(alias) for h in hosts)


def _named_in_text(text: str, host: str, label: str, alias: str) -> bool:
    hosts = set(_HOST.findall(text))
    if host in hosts or _named_by_datadog(hosts, alias):
        return True
    return any(tag.strip() == label for tag in _TAG.findall(text)) or label in _PAIR.findall(text)


def belongs_to(incident: dict[str, Any], host: str, alias: str, databases: list[str]) -> bool:
    host = host.split(":")[0].lower()
    label = host.split(".")[0]
    if incident["websites"]:
        return host in incident["websites"]
    if incident["database"]:
        return incident["database"] in {label, *databases}
    return _named_in_text(incident["text"], host, label, alias)


def iso_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def short_time(value: str) -> str:
    return value[:16].replace("T", " ")


def _incident(row: dict[str, Any]) -> dict[str, Any]:
    assignees = [a.get("assignee", {}).get("summary") for a in row.get("assignments") or []]
    service = row.get("service") or {}

    return {
        "id": _field(row, "id"),
        "number": row.get("incident_number"),
        "title": str(row.get("title") or row.get("summary") or "").strip()[:DETAIL_CHARS],
        "status": row.get("status") or "",
        "urgency": row.get("urgency") or "",
        "priority": (row.get("priority") or {}).get("summary") or "",
        "service": service.get("summary") or "",
        "serviceId": service.get("id") or "",
        "policy": (row.get("escalation_policy") or {}).get("id") or "",
        "created": row.get("created_at") or "",
        "changed": row.get("last_status_change_at") or "",
        "assignees": [a for a in assignees if a],
        "url": row.get("html_url") or "",
        "websites": websites_of(row),
        "database": database_of(row),
        "text": _text_of(row),
    }


def public(incident: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in incident.items() if k != "text"}


def incidents(
    start: int,
    end: int,
    statuses: list[str] | None = None,
    limit: int = INCIDENTS_LIMIT,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "since": iso_utc(start),
        "until": iso_utc(end),
        "sort_by": "created_at:desc",
        "time_zone": "UTC",
        "include[]": ["first_trigger_log_entries"],
    }
    if statuses:
        params["statuses[]"] = statuses

    with client() as pd:
        rows = [_incident(r) for r in pd.pages("/incidents", "incidents", "incidents", limit, **params)]
    learn_databases(rows)
    return rows


def _host_key(host: str) -> str:
    return host.split(":")[0].lower()


def for_instance(rows: list[dict[str, Any]], alias: str) -> list[dict[str, Any]]:
    found = _instance_of(alias)
    main = main_alias(found["alias"])
    databases = load_state().get("databases", {}).get(_host_key(found["host"]), [])
    return [r for r in rows if belongs_to(r, found["host"], main, databases)]


def _incident_ref(value: str) -> str:
    text = value.strip()
    link = re.search(r"/incidents/([A-Za-z0-9]+)", text)
    return link.group(1) if link else text.lstrip("#")


def _timeline_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": entry.get("created_at") or "",
        "type": str(entry.get("type") or "").replace("_log_entry", ""),
        "summary": str(entry.get("summary") or "")[:DETAIL_CHARS],
        "by": (entry.get("agent") or {}).get("summary") or "",
    }


def _alert_entry(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": alert.get("created_at") or "",
        "status": alert.get("status") or "",
        "summary": str(alert.get("summary") or "")[:DETAIL_CHARS],
        "details": _alert_details(alert),
    }


def _note_entry(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": note.get("created_at") or "",
        "by": (note.get("user") or {}).get("summary") or "",
        "text": str(note.get("content") or "")[:TEXT_CHARS],
    }


def incident_detail(ref: str) -> dict[str, Any]:
    ident = _incident_ref(ref)
    if not ident:
        raise PagerDutyError("Give an incident number, id or link.")

    with client() as pd:
        incident = _incident(_field(pd.get(f"/incidents/{ident}", "incidents"), "incident"))
        base = f"/incidents/{incident['id']}"
        sections = [
            (f"{base}/log_entries", "log_entries", {"limit": LOG_ENTRIES_LIMIT}),
            (f"{base}/alerts", "alerts", {"limit": ALERTS_LIMIT}),
            (f"{base}/notes", "notes", {}),
        ]
        with ThreadPoolExecutor(max_workers=len(sections)) as pool:
            parts = {key: pool.submit(pd.get, path, "incidents", **params) for path, key, params in sections}
            found = {key: _field(part.result(), key) for key, part in parts.items()}

    incident["timeline"] = [_timeline_entry(e) for e in reversed(found["log_entries"])]
    incident["alerts"] = [_alert_entry(a) for a in found["alerts"]]
    incident["notes"] = [_note_entry(n) for n in found["notes"]]
    return incident


def _alert_details(alert: dict[str, Any]) -> str:
    body = alert.get("body") or {}
    details = body.get("details") if isinstance(body, dict) else None
    if details is None:
        return ""

    text = details if isinstance(details, str) else json.dumps(details, indent=1)
    return text[:TEXT_CHARS]


def oncall(policy_ids: list[str], at: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"earliest": "true"}
    if policy_ids:
        params["escalation_policy_ids[]"] = sorted(set(policy_ids))
    if at is not None:
        params["since"] = iso_utc(at)
        params["until"] = iso_utc(at + ONCALL_WINDOW_MS)

    with client() as pd:
        rows = pd.pages("/oncalls", "oncalls", "oncall", ONCALLS_LIMIT, **params)
    out = [
        {
            "user": (r.get("user") or {}).get("summary") or "",
            "level": r.get("escalation_level") or 0,
            "policy": (r.get("escalation_policy") or {}).get("summary") or "",
            "schedule": (r.get("schedule") or {}).get("summary") or "",
            "until": r.get("end") or "",
        }
        for r in rows
    ]
    return sorted(out, key=lambda r: (r["policy"], r["level"], r["user"]))


def _add_incidents(report: dict[str, Any], alias: str, start: int, end: int) -> None:
    open_since = end - OPEN_LOOKBACK_DAYS * DAY_MS
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            opened = pool.submit(incidents, open_since, end, OPEN_STATUSES)
            window = pool.submit(incidents, start, end)
            report["open"] = [public(r) for r in for_instance(opened.result(), alias)]
            report["incidents"] = [public(r) for r in for_instance(window.result(), alias)]
    except PagerDutyError as exc:
        report["errors"]["incidents"] = str(exc)


def _add_oncall(report: dict[str, Any]) -> None:
    policies = [r["policy"] for r in report.get("open", []) + report.get("incidents", [])]
    if not policies:
        return

    try:
        report["oncall"] = [o for o in oncall(policies) if o["level"] == 1]
    except PagerDutyError as exc:
        report["errors"]["oncall"] = str(exc)


def health(alias: str, start: int, end: int, key: str) -> dict[str, Any] | None:
    if not connected():
        return None

    cache_key = (alias, key)
    cached = _health_cache.get(cache_key)
    if cached and time.time() - cached[0] < HEALTH_TTL_SECONDS:
        return cached[1]

    report: dict[str, Any] = {"webUrl": web_url(load_state()), "errors": {}}
    allowed = permissions()
    if allowed["incidents"]:
        _add_incidents(report, alias, start, end)
    if allowed["oncall"]:
        _add_oncall(report)

    _health_cache[cache_key] = (time.time(), report)
    return report


def resolve_host(instance: str | None, current: str) -> str:
    target = (instance or current).strip()
    if not target:
        return ""
    return _instance_of(target)["alias"]
