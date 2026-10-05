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
    _save_state({"matches": state.get("matches") or {}, "subdomain": state.get("subdomain")})
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
        "matches": state.get("matches") or {},
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


# Matches are per host: Datadog and PagerDuty see servers, not tenants.
def main_alias(alias: str) -> str:
    found = find_instance(alias)
    if found is None:
        return alias
    same = [i for i in instances() if i["host"] == found["host"]]
    same.sort(key=lambda i: bool(i["tenant"]))
    return same[0]["alias"] if same else alias


def save_matches(matches: dict[str, list[str]]) -> dict[str, Any]:
    state = load_state()
    cleaned = {
        k: sorted({str(x) for x in v if x}) for k, v in matches.items() if isinstance(v, list)
    }
    state["matches"] = {k: v for k, v in cleaned.items() if v}
    _save_state(state)
    _health_cache.clear()
    return status()


def services_for(alias: str) -> list[str]:
    matches = load_state().get("matches") or {}
    return list(matches.get(main_alias(alias)) or matches.get(alias) or [])


def _words(value: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", value.lower()) if len(w) > 1}


def suggest() -> dict[str, Any]:
    rows = services(refresh=True)
    out = []
    seen: set[str] = set()
    for inst in instances():
        alias = main_alias(inst["alias"])
        if alias in seen:
            continue
        seen.add(alias)
        host = inst["host"].split(":")[0].lower()
        label = host.split(".")[0]
        picked = [
            s["id"]
            for s in rows
            if host in f"{s['name']} {s['description']}".lower()
            or label in _words(f"{s['name']} {s['description']}")
        ]
        out.append({"alias": alias, "host": inst["host"], "services": picked})
    return {"services": rows, "suggestions": out}


def iso_utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short_time(value: str | None) -> str:
    return str(value or "")[:16].replace("T", " ")


def _incident(row: dict[str, Any]) -> dict[str, Any]:
    assignees = [a.get("assignee", {}).get("summary") for a in row.get("assignments") or []]
    return {
        "id": row.get("id") or "",
        "number": row.get("incident_number"),
        "title": str(row.get("title") or row.get("summary") or "")[:300],
        "status": row.get("status") or "",
        "urgency": row.get("urgency") or "",
        "priority": (row.get("priority") or {}).get("summary") or "",
        "service": (row.get("service") or {}).get("summary") or "",
        "serviceId": (row.get("service") or {}).get("id") or "",
        "created": row.get("created_at") or "",
        "changed": row.get("last_status_change_at") or "",
        "assignees": [a for a in assignees if a],
        "url": row.get("html_url") or "",
    }


def incidents(
    service_ids: list[str] | None,
    start: int,
    end: int,
    statuses: list[str] | None = None,
    limit: int = MAX_INCIDENTS,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "since": iso_utc(start),
        "until": iso_utc(end),
        "sort_by": "created_at:desc",
        "time_zone": "UTC",
    }
    if service_ids:
        params["service_ids[]"] = service_ids
    if statuses:
        params["statuses[]"] = statuses
    with client() as pd:
        rows = pd.pages("/incidents", "incidents", "incidents", limit, **params)
    return [_incident(r) for r in rows]


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


def oncall(service_ids: list[str], at: int | None = None) -> list[dict[str, Any]]:
    by_id = {s["id"]: s for s in services()}
    policies = sorted(
        {by_id[s]["policy"] for s in service_ids if s in by_id and by_id[s]["policy"]}
    )
    if service_ids and not policies:
        return []
    params: dict[str, Any] = {"earliest": "true"}
    if policies:
        params["escalation_policy_ids[]"] = policies
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
    ids = services_for(alias)
    report: dict[str, Any] = {"services": ids, "webUrl": web_url(), "errors": {}}
    if not ids:
        report["errors"]["match"] = "No PagerDuty service is matched to this instance."
        return report
    allowed = permissions()

    def run(name: str, fn: Any) -> None:
        try:
            report[name] = fn()
        except PagerDutyError as exc:
            report["errors"][name] = str(exc)

    open_since = end - OPEN_LOOKBACK_DAYS * 86_400_000
    jobs: list[tuple[str, Any]] = []
    if allowed["incidents"]:
        jobs += [
            ("open", lambda: incidents(ids, open_since, end, ["triggered", "acknowledged"])),
            ("incidents", lambda: incidents(ids, start, end)),
        ]
    if allowed["oncall"]:
        jobs.append(("oncall", lambda: [o for o in oncall(ids) if o["level"] == 1]))
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda job: run(*job), jobs))
    _health_cache[cache_key] = (time.time(), report)
    return report


def resolve_services(instance: str | None, fallback: str) -> tuple[str, list[str]]:
    target = (instance or fallback or "").strip()
    if not target:
        return "", []
    found = find_instance(target)
    if found is None:
        raise PagerDutyError(f"No signed-in instance matches {target}.")
    ids = services_for(found["alias"])
    if not ids:
        raise PagerDutyError(
            f"{found['host']} is not matched to a PagerDuty service yet. Match it in Settings > "
            "Integrations > PagerDuty, or pass all_services=true to search every service."
        )
    return found["host"], ids
