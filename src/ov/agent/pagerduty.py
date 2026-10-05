from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from .. import credentials
from ..paths import agent_dir, write_atomic
from .ovproc import find_instance, instances

CREDENTIAL_KEY = "agent:pagerduty"
TIMEOUT_SECONDS = 30
MAX_INCIDENTS = 50
TEXT_CHARS = 600
SERVICES_TTL_SECONDS = 600
HEALTH_TTL_SECONDS = 60
OPEN_LOOKBACK_DAYS = 30

REGIONS = {"us": "https://api.pagerduty.com", "eu": "https://api.eu.pagerduty.com"}
AREAS = ("incidents", "services", "oncall")

# Tests swap in a fake PagerDuty here.
TRANSPORT: httpx.BaseTransport | None = None

_lock = threading.Lock()
_services_cache: tuple[float, list[dict[str, Any]]] | None = None
_health_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


class PagerDutyError(Exception):
    pass


# Accepts "onevizion", "onevizion.pagerduty.com" or any URL from the account.
def account_of(value: str) -> tuple[str, str]:
    text = value.strip().lower()
    if not text:
        return "", "us"
    host = urlsplit(text if "://" in text else f"https://{text}").hostname or text
    if host in ("api.pagerduty.com", "api.eu.pagerduty.com"):
        return "", "eu" if ".eu." in host else "us"
    if not host.endswith("pagerduty.com"):
        if re.fullmatch(r"[a-z0-9-]+", host):
            return host, "us"
        raise PagerDutyError(f"Not a PagerDuty address: {value}")
    region = "eu" if host.endswith(".eu.pagerduty.com") else "us"
    sub = host.split(".")[0]
    return ("" if sub in ("app", "www", "eu") else sub), region


def _state_file():
    return agent_dir() / "pagerduty.json"


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


def _key() -> str | None:
    secret = (credentials.get(CREDENTIAL_KEY) or {}).get("api_key")
    return str(secret) if secret else None


def connected() -> bool:
    return bool(load_state().get("region")) and _key() is not None


def permissions() -> dict[str, bool]:
    stored = load_state().get("permissions") or {}
    return {area: bool(stored.get(area)) for area in AREAS}


def web_url(state: dict[str, Any] | None = None) -> str:
    state = state if state is not None else load_state()
    sub = state.get("subdomain") or ""
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

    def get(self, path: str, area: str = "", **params: Any) -> dict[str, Any]:
        for attempt in range(2):
            try:
                response = self._http.get(path, params=params)
            except httpx.HTTPError as exc:
                raise PagerDutyError(f"Could not reach PagerDuty: {exc}") from None
            if response.status_code == 429 and attempt == 0:
                time.sleep(2)
                continue
            break
        if response.status_code < 400:
            return response.json() if response.content else {}
        raise PagerDutyError(_explain(response, area))

    def pages(self, path: str, key: str, area: str, limit: int, **params: Any) -> list[dict]:
        out: list[dict[str, Any]] = []
        offset = 0
        while len(out) < limit:
            data = self.get(path, area, limit=min(100, limit - len(out)), offset=offset, **params)
            rows = data.get(key) or []
            out += rows
            if not data.get("more") or not rows:
                break
            offset += len(rows)
        return out


def _explain(response: httpx.Response, area: str) -> str:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        error = {}
    detail = "; ".join([str(error.get("message") or ""), *map(str, error.get("errors") or [])])
    if response.status_code == 401:
        return "PagerDuty rejected the API key (wrong key, or a key for the other region)."
    if response.status_code == 403:
        what = f" ({area})" if area else ""
        return f"PagerDuty refused this request{what}: your user cannot read it."
    if response.status_code == 404:
        return "PagerDuty has no such incident or object."
    if response.status_code == 429:
        return "PagerDuty rate limit reached. Try again in a minute."
    return f"PagerDuty returned {response.status_code}: {detail.strip('; ') or response.text[:200]}"


def client() -> Client:
    state = load_state()
    key = _key()
    if not state.get("region") or key is None:
        raise PagerDutyError("PagerDuty is not connected. Connect it in Settings > Integrations.")
    return Client(state["region"], key)


def _probe(pd: Client, area: str) -> bool:
    path = {"incidents": "/incidents", "services": "/services", "oncall": "/oncalls"}[area]
    try:
        pd.get(path, area, limit=1)
    except PagerDutyError:
        return False
    return True


def check(region: str, api_key: str) -> tuple[dict[str, Any], dict[str, bool]]:
    api_key = api_key.strip()
    if not api_key:
        raise PagerDutyError("Paste your API user token.")
    with Client(region, api_key) as pd:
        try:
            me = pd.get("/users/me").get("user") or {}
        except PagerDutyError as exc:
            raise PagerDutyError(
                f"{exc} Use a User API token from My Profile > User Settings."
            ) from None
        with ThreadPoolExecutor(max_workers=len(AREAS)) as pool:
            found = dict(zip(AREAS, pool.map(lambda a: _probe(pd, a), AREAS), strict=True))
    return me, found


def connect(account: str, api_key: str) -> dict[str, Any]:
    sub, region = account_of(account)
    me, found = check(region, api_key)
    credentials.put(CREDENTIAL_KEY, {"api_key": api_key.strip()})
    html = str(me.get("html_url") or "")
    if not sub and ".pagerduty.com" in html:
        sub = urlsplit(html).hostname.split(".")[0]  # type: ignore[union-attr]
    state = load_state()
    state.update(
        {
            "region": region,
            "subdomain": sub,
            "user": me.get("name") or me.get("email") or "",
            "email": me.get("email") or "",
            "keyLast4": api_key.strip()[-4:],
            "permissions": found,
            "checkedAt": int(time.time() * 1000),
            "error": None,
        }
    )
    _save_state(state)
    _forget_caches()
    return status()


def retest() -> dict[str, Any]:
    state = load_state()
    key = _key()
    if not state.get("region") or key is None:
        raise PagerDutyError("PagerDuty is not connected.")
    try:
        _, state["permissions"] = check(state["region"], key)
        state["error"] = None
    except PagerDutyError as exc:
        state["error"] = str(exc)
    state["checkedAt"] = int(time.time() * 1000)
    _save_state(state)
    _forget_caches()
    return status()


def disconnect() -> dict[str, Any]:
    credentials.delete(CREDENTIAL_KEY)
    state = load_state()
    _save_state({"subdomain": state.get("subdomain")})
    _forget_caches()
    return status()


def _forget_caches() -> None:
    global _services_cache
    _services_cache = None
    _health_cache.clear()


def status() -> dict[str, Any]:
    state = load_state()
    on = connected()
    return {
        "connected": on,
        "region": state.get("region") or "us",
        "subdomain": state.get("subdomain") or "",
        "webUrl": web_url(state),
        "user": state.get("user") if on else None,
        "email": state.get("email") if on else None,
        "keyLast4": state.get("keyLast4") if on else None,
        "permissions": permissions() if on else {a: False for a in AREAS},
        "checkedAt": state.get("checkedAt") if on else None,
        "error": state.get("error") if on else None,
    }


def services(refresh: bool = False) -> list[dict[str, Any]]:
    global _services_cache
    if _services_cache and not refresh and time.time() - _services_cache[0] < SERVICES_TTL_SECONDS:
        return _services_cache[1]
    with client() as pd:
        rows = pd.pages("/services", "services", "services", 2000)
    out = [
        {
            "id": s.get("id"),
            "name": s.get("name") or s.get("summary") or "",
            "description": str(s.get("description") or "")[:200],
            "status": s.get("status") or "",
            "policy": (s.get("escalation_policy") or {}).get("id") or "",
            "url": s.get("html_url") or "",
        }
        for s in rows
        if s.get("id")
    ]
    out.sort(key=lambda s: s["name"].lower())
    _services_cache = (time.time(), out)
    return out


# Services are shared, so incidents are tied to instances by what their alert names:
# OV monitoring sends details.website (or details.database for database alerts), and
# Datadog names the host, a tag such as dbinstanceidentifier:<name>, or [Instance].
_HOST = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+\b")
_TAG = re.compile(r"\[([a-z0-9][a-z0-9 _-]*)\]")
_PAIR = re.compile(r"\b[a-z_]+:([a-z0-9][a-z0-9_-]*)")
WEBSITE_KEYS = ("website", "host", "hostname", "url", "client_url")
EMPTY = {"", "none", "null", "n/a", "na", "-", "unknown"}


def main_alias(alias: str) -> str:
    found = find_instance(alias)
    if found is None:
        return alias
    same = [i for i in instances() if i["host"] == found["host"]]
    same.sort(key=lambda i: bool(i["tenant"]))
    return same[0]["alias"] if same else alias


def _channel(row: dict[str, Any]) -> dict[str, Any]:
    return (row.get("first_trigger_log_entry") or {}).get("channel") or {}


def websites_of(row: dict[str, Any]) -> list[str]:
    details = _channel(row).get("details")
    found: list[str] = []
    if isinstance(details, dict):
        for key in WEBSITE_KEYS:
            value = str(details.get(key) or "").strip().lower()
            if value not in EMPTY:
                found.append(urlsplit(value if "://" in value else f"//{value}").hostname or value)
    return [w for w in dict.fromkeys(found) if w and w not in EMPTY]


def database_of(row: dict[str, Any]) -> str:
    details = _channel(row).get("details")
    value = str(details.get("database") or "").strip().lower() if isinstance(details, dict) else ""
    return "" if value in EMPTY else value


# Website alerts name both the website and its database; remember the pairs so a later
# database-only alert can be tied to every instance on that database.
def learn_databases(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    state = load_state()
    known: dict[str, list[str]] = {k: list(v) for k, v in (state.get("databases") or {}).items()}
    changed = False
    for r in rows:
        if r["database"]:
            for site in r["websites"]:
                if r["database"] not in known.setdefault(site, []):
                    known[site].append(r["database"])
                    changed = True
    if changed:
        state["databases"] = known
        _save_state(state)
    return known


def _text_of(row: dict[str, Any]) -> str:
    channel = _channel(row)
    parts = [row.get("title"), row.get("summary"), channel.get("summary"), channel.get("details")]
    return " ".join(json.dumps(p) if isinstance(p, dict) else str(p or "") for p in parts).lower()


def _datadog_hosts(alias: str) -> list[tuple[str, bool]]:
    from . import datadog

    try:
        scope = datadog.filter_for(alias)
    except Exception:
        return []
    out = []
    for tag in scope.split():
        name, _, value = tag.partition(":")
        if name == "host" and value:
            out.append((value.lower().rstrip("*"), value.endswith("*")))
    return out


def belongs_to(
    incident: dict[str, Any], host: str, alias: str = "", databases: list[str] | None = None
) -> bool:
    host = host.split(":")[0].lower()
    label = host.split(".")[0]
    if host in incident["websites"]:
        return True
    if incident["websites"]:
        return False
    if incident["database"]:
        return incident["database"] in {label, *(databases or [])}
    text = incident["text"]
    hosts = set(_HOST.findall(text))
    if host in hosts:
        return True
    for value, prefix in _datadog_hosts(alias) if alias else []:
        if any(h == value or (prefix and h.startswith(value)) for h in hosts):
            return True
    if any(tag.strip() == label for tag in _TAG.findall(text)):
        return True
    return label in _PAIR.findall(text)


def iso_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short_time(value: str | None) -> str:
    return str(value or "")[:16].replace("T", " ")


def _incident(row: dict[str, Any]) -> dict[str, Any]:
    assignees = [a.get("assignee", {}).get("summary") for a in row.get("assignments") or []]
    return {
        "id": row.get("id") or "",
        "number": row.get("incident_number"),
        "title": str(row.get("title") or row.get("summary") or "").strip()[:300],
        "status": row.get("status") or "",
        "urgency": row.get("urgency") or "",
        "priority": (row.get("priority") or {}).get("summary") or "",
        "service": (row.get("service") or {}).get("summary") or "",
        "serviceId": (row.get("service") or {}).get("id") or "",
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
    limit: int = 1000,
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
        rows = [
            _incident(r) for r in pd.pages("/incidents", "incidents", "incidents", limit, **params)
        ]
    learn_databases(rows)
    return rows


def for_instance(rows: list[dict[str, Any]], alias: str) -> list[dict[str, Any]]:
    found = find_instance(alias)
    if found is None:
        return []
    main = main_alias(found["alias"])
    databases = (load_state().get("databases") or {}).get(found["host"].split(":")[0].lower())
    return [r for r in rows if belongs_to(r, found["host"], main, databases)]


# Which signed-in instances (and other websites) recent incidents point at.
def website_map(days: int = 7) -> dict[str, Any]:
    end = int(time.time() * 1000)
    rows = incidents(end - days * 86_400_000, end)
    hosts: dict[str, dict[str, Any]] = {}
    signed = {}
    for inst in instances():
        signed.setdefault(inst["host"], main_alias(inst["alias"]))
    matched_ids: set[str] = set()
    known = load_state().get("databases") or {}
    for host, alias in signed.items():
        mine = [r for r in rows if belongs_to(r, host, alias, known.get(host))]
        if mine:
            matched_ids.update(r["id"] for r in mine)
            hosts[host] = _summary(host, alias, mine)
    for r in rows:
        if r["id"] in matched_ids:
            continue
        site_of_db = {d: s for s, dbs in known.items() for d in dbs if len(dbs) == 1}
        fallback = site_of_db.get(r["database"]) or (
            f"database {r['database']}" if r["database"] else "other"
        )
        names = r["websites"] or [fallback]
        for site in names:
            entry = hosts.setdefault(site, _summary(site, None, []))
            entry["count"] += 1
            entry["open"] += r["status"] != "resolved"
    ordered = sorted(hosts.values(), key=lambda h: (h["alias"] is None, -h["open"], -h["count"]))
    return {"days": days, "total": len(rows), "matched": len(matched_ids), "websites": ordered}


def _summary(host: str, alias: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "host": host,
        "alias": alias,
        "count": len(rows),
        "open": sum(r["status"] != "resolved" for r in rows),
    }


def _incident_ref(value: str) -> str:
    text = value.strip()
    match = re.search(r"/incidents/([A-Za-z0-9]+)", text)
    return match.group(1) if match else text.lstrip("#")


def incident_detail(ref: str) -> dict[str, Any]:
    ident = _incident_ref(ref)
    if not ident:
        raise PagerDutyError("Give an incident number, id or link.")
    with client() as pd:
        incident = _incident(pd.get(f"/incidents/{ident}", "incidents").get("incident") or {})
        key = incident["id"] or ident

        def logs() -> list[dict[str, Any]]:
            data = pd.get(f"/incidents/{key}/log_entries", "incidents", limit=100)
            return data.get("log_entries") or []

        def alerts() -> list[dict[str, Any]]:
            return pd.get(f"/incidents/{key}/alerts", "incidents", limit=25).get("alerts") or []

        def notes() -> list[dict[str, Any]]:
            return pd.get(f"/incidents/{key}/notes", "incidents").get("notes") or []

        with ThreadPoolExecutor(max_workers=3) as pool:
            parts = [pool.submit(f) for f in (logs, alerts, notes)]
            timeline, raw_alerts, raw_notes = (_safe(p) for p in parts)
    incident["timeline"] = [
        {
            "time": e.get("created_at") or "",
            "type": str(e.get("type") or "").replace("_log_entry", ""),
            "summary": str(e.get("summary") or "")[:300],
            "by": (e.get("agent") or {}).get("summary") or "",
        }
        for e in reversed(timeline)
    ]
    incident["alerts"] = [
        {
            "time": a.get("created_at") or "",
            "status": a.get("status") or "",
            "summary": str(a.get("summary") or "")[:300],
            "details": _details(a),
        }
        for a in raw_alerts
    ]
    incident["notes"] = [
        {
            "time": n.get("created_at") or "",
            "by": (n.get("user") or {}).get("summary") or "",
            "text": str(n.get("content") or "")[:TEXT_CHARS],
        }
        for n in raw_notes
    ]
    return incident


def _safe(future: Any) -> list[dict[str, Any]]:
    try:
        return future.result()
    except PagerDutyError:
        return []


def _details(alert: dict[str, Any]) -> str:
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
    if at:
        params["since"] = iso_utc(at)
        params["until"] = iso_utc(at + 60_000)
    with client() as pd:
        rows = pd.pages("/oncalls", "oncalls", "oncall", 200, **params)
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


def health(alias: str, start: int, end: int, key: str) -> dict[str, Any] | None:
    if not connected():
        return None
    cache_key = (alias, key)
    cached = _health_cache.get(cache_key)
    if cached and time.time() - cached[0] < HEALTH_TTL_SECONDS:
        return cached[1]
    report: dict[str, Any] = {"webUrl": web_url(), "errors": {}}
    allowed = permissions()
    if allowed["incidents"]:
        try:
            open_since = end - OPEN_LOOKBACK_DAYS * 86_400_000
            with ThreadPoolExecutor(max_workers=2) as pool:
                opened = pool.submit(incidents, open_since, end, ["triggered", "acknowledged"])
                window = pool.submit(incidents, start, end)
                report["open"] = [public(r) for r in for_instance(opened.result(), alias)]
                report["incidents"] = [public(r) for r in for_instance(window.result(), alias)]
        except PagerDutyError as exc:
            report["errors"]["incidents"] = str(exc)
    policies = [r["policy"] for r in report.get("open", []) + report.get("incidents", [])]
    if allowed["oncall"] and policies:
        try:
            report["oncall"] = [o for o in oncall(policies) if o["level"] == 1]
        except PagerDutyError as exc:
            report["errors"]["oncall"] = str(exc)
    _health_cache[cache_key] = (time.time(), report)
    return report


def resolve_host(instance: str | None, fallback: str) -> str:
    target = (instance or fallback or "").strip()
    if not target:
        return ""
    found = find_instance(target)
    if found is None:
        raise PagerDutyError(f"No signed-in instance matches {target}.")
    return found["alias"]
