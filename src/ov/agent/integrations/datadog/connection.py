from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from ov.agent.integrations.common import HttpClient, Service, TimedCache, explain, payload
from ov.core import credentials

CREDENTIAL_KEY = "agent:datadog"
TIMEOUT_SECONDS = 30
RATE_LIMIT_WAIT_SECONDS = 2.0
MAX_RATE_LIMIT_WAIT_SECONDS = 10.0
HEALTH_TTL_SECONDS = 60
DATABASE_TTL_SECONDS = 600

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
STATUS_MESSAGES = {
    401: "Datadog rejected the API key (wrong key, or a key for another site).",
    429: "Datadog rate limit reached. Try again in a minute.",
}

TRANSPORT: httpx.BaseTransport | None = None

health_cache = TimedCache(HEALTH_TTL_SECONDS)
database_cache = TimedCache(DATABASE_TTL_SECONDS)


class DatadogError(Exception):
    pass


def clear_caches() -> None:
    health_cache.clear()
    database_cache.clear()


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
save_state = SERVICE.save_state
stored = SERVICE.stored
field = SERVICE.field


def stored_keys() -> tuple[str, str] | None:
    secrets = credentials.get(CREDENTIAL_KEY)
    if secrets is None:
        return None
    if not secrets.get("api_key") or not secrets.get("app_key"):
        raise DatadogError("The stored Datadog keys are incomplete. Reconnect Datadog in Settings > Integrations.")
    return str(secrets["api_key"]), str(secrets["app_key"])


def connected() -> bool:
    return "site" in load_state() and stored_keys() is not None


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
    keys = stored_keys()
    if "site" not in state or keys is None:
        raise DatadogError("Datadog is not connected. Connect it in Settings > Integrations.")
    return Client(state["site"], *keys)
