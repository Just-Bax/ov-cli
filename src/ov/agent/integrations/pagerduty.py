from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from ov.agent.instances.ovproc import find_instance, instances
from ov.agent.integrations import datadog
from ov.agent.integrations.common import HttpClient, Service, TimedCache, explain, payload
from ov.agent.storage.db import now_ms
from ov.core import credentials

CREDENTIAL_KEY = "agent:pagerduty"
TIMEOUT_SECONDS = 30
RATE_LIMIT_WAIT_SECONDS = 2
PAGE_SIZE = 100
MAX_INCIDENTS = 50
INCIDENTS_LIMIT = 1000
ONCALLS_LIMIT = 200
LOG_ENTRIES_LIMIT = 100
ALERTS_LIMIT = 25
TEXT_CHARS = 600
DETAIL_CHARS = 300
HEALTH_TTL_SECONDS = 60
OPEN_LOOKBACK_DAYS = 30
DAY_MS = 86_400_000
ONCALL_WINDOW_MS = 60_000
MAX_SNOOZE_MINUTES = 1440
DIRECTORY_LIMIT = 200
FIND_SHOWN = 8
INCIDENT_WORKERS = 2
KEY_TAIL_CHARS = 4
ISO_MINUTES_CHARS = 16
SECONDS_PER_MINUTE = 60

REGIONS = {"us": "https://api.pagerduty.com", "eu": "https://api.eu.pagerduty.com"}
ACCOUNT_URL = "https://{subdomain}{region}.pagerduty.com"
APP_SUBDOMAIN = "app"
DEFAULT_REGION = "us"
NON_ACCOUNT_SUBDOMAINS = ("app", "www", "eu", "api")
AREAS = ("incidents", "oncall")
PROBE_PATHS = {"incidents": "/incidents", "oncall": "/oncalls"}
OPEN_STATUSES = ["triggered", "acknowledged"]
STATUS_MESSAGES = {
    401: "PagerDuty rejected the API key (wrong key, or a key for the other region).",
    404: "PagerDuty has no such incident or object.",
    429: "PagerDuty rate limit reached. Try again in a minute.",
}

TRANSPORT: httpx.BaseTransport | None = None

_health_cache = TimedCache(HEALTH_TTL_SECONDS)


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


SERVICE = Service("PagerDuty", "pagerduty.json", "region", PagerDutyError)
load_state = SERVICE.load_state
_save_state = SERVICE.save_state
_field = SERVICE.field


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
    return SERVICE.permissions(AREAS)


def web_url(state: dict[str, Any]) -> str:
    sub = state.get("subdomain", "")
    eu = ".eu" if state.get("region") == "eu" else ""
    return ACCOUNT_URL.format(subdomain=sub or APP_SUBDOMAIN, region=eu)


def _rate_limit_wait(_response: httpx.Response) -> float:
    return RATE_LIMIT_WAIT_SECONDS


class Client(HttpClient):
    def __init__(self, region: str, api_key: str) -> None:
        super().__init__(
            SERVICE,
            REGIONS[region],
            {"Authorization": f"Token token={api_key}", "Accept": "application/vnd.pagerduty+json;version=2"},
            timeout=TIMEOUT_SECONDS,
            transport=TRANSPORT,
            rate_limit_wait=_rate_limit_wait,
        )

    def get(self, path: str, area: str = "", **params: Any) -> dict[str, Any]:
        response = self.send("GET", path, params=params)
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise PagerDutyError(_explain(response, area))
        return payload(response)

    def write(self, method: str, path: str, body: dict[str, Any], email: str) -> dict[str, Any]:
        response = self.send(method, path, json=body, headers={"From": email})
        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise PagerDutyError(
                "PagerDuty refused this change. The token may be read-only, or your role cannot do it: "
                "create a full-access User API token and reconnect PagerDuty in Settings > Integrations."
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise PagerDutyError(_explain(response, "incidents"))
        return payload(response)

    def pages(self, path: str, key: str, area: str, limit: int, **params: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while len(out) < limit:
            data = self.get(path, area, limit=min(PAGE_SIZE, limit - len(out)), offset=len(out), **params)
            rows = _field(data, key)
            out += rows
            if not _field(data, "more") or not rows:
                break
        return out


def _errors_in(body: Any) -> str:
    error = body.get("error") or {}
    return "; ".join([str(error.get("message") or ""), *map(str, error.get("errors") or [])]).strip("; ")


def _explain(response: httpx.Response, area: str) -> str:
    what = f" ({area})" if area else ""
    forbidden = f"PagerDuty refused this request{what}: your user cannot read it."
    return explain(SERVICE, response, STATUS_MESSAGES, forbidden, _errors_in)


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
            "keyLast4": api_key[-KEY_TAIL_CHARS:],
            "permissions": found,
            "checkedAt": now_ms(),
            "error": None,
        }
    )
    _save_state(state)
    _health_cache.clear()
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
    state["checkedAt"] = now_ms()
    _save_state(state)
    _health_cache.clear()
    return status()


def disconnect() -> dict[str, Any]:
    credentials.delete(CREDENTIAL_KEY)
    state = load_state()
    _save_state({"subdomain": state["subdomain"]} if "subdomain" in state else {})
    _health_cache.clear()
    return status()


def status() -> dict[str, Any]:
    state = load_state()
    on = connected()
    private = ("user", "email", "keyLast4", "checkedAt", "error")
    details = SERVICE.details(state, on, private)

    return {
        "connected": on,
        "region": state.get("region", DEFAULT_REGION),
        "subdomain": state.get("subdomain", ""),
        "webUrl": web_url(state),
        **details,
        "permissions": permissions() if on else dict.fromkeys(AREAS, False),
    }


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
    return value[:ISO_MINUTES_CHARS].replace("T", " ")


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
        with ThreadPoolExecutor(max_workers=INCIDENT_WORKERS) as pool:
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
    if cached is not None:
        return cached

    report: dict[str, Any] = {"webUrl": web_url(load_state()), "errors": {}}
    allowed = permissions()
    if allowed["incidents"]:
        _add_incidents(report, alias, start, end)
    if allowed["oncall"]:
        _add_oncall(report)

    _health_cache.put(cache_key, report)
    return report


def resolve_host(instance: str | None, current: str) -> str:
    target = (instance or current).strip()
    if not target:
        return ""
    return _instance_of(target)["alias"]


def _email() -> str:
    email = load_state().get("email", "")
    if not email:
        raise PagerDutyError("PagerDuty did not give your email, which changes need. Reconnect PagerDuty in Settings.")
    return email


def _target(pd: Client, ref: str) -> dict[str, Any]:
    ident = _incident_ref(ref)
    if not ident:
        raise PagerDutyError("Give an incident number, id or link.")
    return _incident(_field(pd.get(f"/incidents/{ident}", "incidents"), "incident"))


def _update(ref: str, fields: dict[str, Any]) -> dict[str, Any]:
    with client() as pd:
        found = _target(pd, ref)
        body = {"incident": {"type": "incident_reference", **fields}}
        updated = _incident(_field(pd.write("PUT", f"/incidents/{found['id']}", body, _email()), "incident"))
    _health_cache.clear()
    return updated


def describe(ref: str) -> dict[str, Any]:
    with client() as pd:
        return _target(pd, ref)


def add_note(ref: str, text: str) -> dict[str, Any]:
    if not text.strip():
        raise PagerDutyError("A note needs text.")

    with client() as pd:
        found = _target(pd, ref)
        pd.write("POST", f"/incidents/{found['id']}/notes", {"note": {"content": text.strip()}}, _email())
    _health_cache.clear()
    return found


def set_status(ref: str, status: str) -> dict[str, Any]:
    if status not in ("acknowledged", "resolved"):
        raise PagerDutyError(f"Unknown status {status}.")
    return _update(ref, {"status": status})


def escalate(ref: str, level: int) -> dict[str, Any]:
    if level < 1:
        raise PagerDutyError("Escalation levels start at 1.")
    return _update(ref, {"escalation_level": level})


def reassign(ref: str, policy_id: str | None, user_ids: list[str]) -> dict[str, Any]:
    if bool(policy_id) == bool(user_ids):
        raise PagerDutyError("Reassign to either an escalation policy or users, not both and not neither.")
    if policy_id:
        return _update(ref, {"escalation_policy": {"id": policy_id, "type": "escalation_policy_reference"}})
    assignments = [{"assignee": {"id": uid, "type": "user_reference"}} for uid in user_ids]
    return _update(ref, {"assignments": assignments})


def snooze(ref: str, minutes: int) -> dict[str, Any]:
    if not 1 <= minutes <= MAX_SNOOZE_MINUTES:
        raise PagerDutyError(f"Snooze for 1 to {MAX_SNOOZE_MINUTES} minutes.")

    with client() as pd:
        found = _target(pd, ref)
        if found["status"] != "acknowledged":
            raise PagerDutyError("Only an acknowledged incident can be snoozed. Acknowledge it first.")
        pd.write("POST", f"/incidents/{found['id']}/snooze", {"duration": minutes * SECONDS_PER_MINUTE}, _email())
    _health_cache.clear()
    return found


def policies(query: str) -> list[dict[str, Any]]:
    with client() as pd:
        rows = pd.pages("/escalation_policies", "escalation_policies", "incidents", DIRECTORY_LIMIT, query=query)
    return [{"id": _field(r, "id"), "name": r.get("name") or r.get("summary") or ""} for r in rows]


def users(query: str) -> list[dict[str, Any]]:
    with client() as pd:
        rows = pd.pages("/users", "users", "incidents", DIRECTORY_LIMIT, query=query)
    return [{"id": _field(r, "id"), "name": r.get("name") or "", "email": r.get("email") or ""} for r in rows]


def find_one(kind: str, value: str) -> dict[str, Any]:
    if re.fullmatch(r"P[A-Z0-9]{5,}", value.strip()):
        return {"id": value.strip(), "name": value.strip()}

    rows = policies(value) if kind == "policy" else users(value)
    wanted = value.strip().lower()
    exact = [r for r in rows if wanted in (r["name"].lower(), r.get("email", "").lower())]
    picked = exact or rows
    if len(picked) != 1:
        names = ", ".join(r["name"] for r in picked[:FIND_SHOWN]) or "none"
        raise PagerDutyError(f"{len(picked)} PagerDuty {kind} match {value!r}: {names}. Be more specific.")
    return picked[0]
