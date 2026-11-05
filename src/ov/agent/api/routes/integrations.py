from __future__ import annotations

from typing import Any

from ov.agent.api.handler import Handler, HttpError, required, route
from ov.agent.api.routes.instances import instance_alias
from ov.agent.instances.maintenance import MaintenanceUnavailable, maintenance_for
from ov.agent.integrations import datadog, pagerduty

DEFAULT_RANGE = "24h"


@route("GET", "/api/datadog")
def datadog_status(_: Handler) -> dict[str, Any]:
    return datadog.status()


@route("POST", "/api/datadog/connect")
def datadog_connect(h: Handler) -> dict[str, Any]:
    data = h.json()
    return datadog.connect(str(data.get("site") or ""), str(data.get("apiKey") or ""), str(data.get("appKey") or ""))


@route("POST", "/api/datadog/test")
def datadog_test(_: Handler) -> dict[str, Any]:
    return datadog.retest()


@route("DELETE", "/api/datadog")
def datadog_disconnect(_: Handler) -> dict[str, Any]:
    return datadog.disconnect()


@route("GET", "/api/datadog/discover")
def datadog_discover(_: Handler) -> dict[str, Any]:
    return datadog.discover()


@route("PUT", "/api/datadog/matches")
def datadog_matches(h: Handler) -> dict[str, Any]:
    matches = h.json().get("matches")
    if not isinstance(matches, dict):
        raise HttpError(400, "Give matches as an object of instance alias to Datadog filter.")
    return datadog.save_matches({str(k): str(v) for k, v in matches.items()})


@route("GET", "/api/datadog/databases")
def datadog_databases(_: Handler) -> dict[str, Any]:
    return {"databases": datadog.database_catalog()}


@route("POST", "/api/datadog/databases/discover")
def datadog_discover_databases(h: Handler) -> dict[str, Any]:
    matches = h.json().get("matches")
    if not isinstance(matches, dict):
        raise HttpError(400, "Give matches as an object of instance alias to Datadog filter.")
    return datadog.discover_databases({str(k): str(v) for k, v in matches.items()})


@route("PUT", "/api/datadog/databases")
def datadog_pick_databases(h: Handler) -> dict[str, Any]:
    databases = h.json().get("databases")
    if not isinstance(databases, dict) or not all(isinstance(v, list) for v in databases.values()):
        raise HttpError(400, "Give databases as an object of instance alias to a list of database ids.")
    return datadog.save_databases({str(k): [str(i) for i in v] for k, v in databases.items()})


def _incidents(alias: str, start: int, end: int, range_key: str) -> dict[str, Any]:
    report = pagerduty.health(alias, start, end, range_key)
    if report is None:
        raise datadog.Unavailable("PagerDuty is not connected.")
    return report


def _datadog_hosts(alias: str) -> list[str]:
    if not datadog.connected():
        return []
    return datadog.hosts_in(datadog.filter_for(alias)) or []


def _health_range(h: Handler) -> str:
    range_key = h.query.get("range", DEFAULT_RANGE)
    if range_key not in datadog.RANGES:
        raise HttpError(400, f"Unknown range: {range_key}")
    return range_key


@route("GET", "/api/instance-health/meta")
def instance_health_meta(h: Handler) -> dict[str, Any]:
    return datadog.health_meta(instance_alias(h), _health_range(h))


@route("GET", "/api/instance-health/([a-z]+)")
def instance_health_section(h: Handler, section: str) -> dict[str, Any]:
    alias = instance_alias(h)
    range_key = _health_range(h)
    end = int(required(h.query, "to"))
    start, _ = datadog.window(range_key, end)

    try:
        if section == "incidents":
            return _incidents(alias, start, end, range_key)
        if section == "maintenance":
            return maintenance_for(alias, _datadog_hosts(alias), end)
        return datadog.health_section(alias, range_key, section, end)
    except (datadog.Unavailable, MaintenanceUnavailable) as exc:
        return {"unavailable": str(exc)}


@route("GET", "/api/pagerduty/incidents/([A-Za-z0-9]+)")
def pagerduty_incident_detail(_: Handler, ident: str) -> dict[str, Any]:
    return pagerduty.public(pagerduty.incident_detail(ident))


@route("GET", "/api/pagerduty")
def pagerduty_status(_: Handler) -> dict[str, Any]:
    return pagerduty.status()


@route("POST", "/api/pagerduty/connect")
def pagerduty_connect(h: Handler) -> dict[str, Any]:
    data = h.json()
    return pagerduty.connect(str(data.get("account") or ""), str(data.get("apiKey") or ""))


@route("POST", "/api/pagerduty/test")
def pagerduty_test(_: Handler) -> dict[str, Any]:
    return pagerduty.retest()


@route("DELETE", "/api/pagerduty")
def pagerduty_disconnect(_: Handler) -> dict[str, Any]:
    return pagerduty.disconnect()
