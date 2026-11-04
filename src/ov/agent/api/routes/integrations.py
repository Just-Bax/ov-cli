from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ov.agent.api.handler import Handler, HttpError, required, route
from ov.agent.api.routes.instances import instance_alias
from ov.agent.engine.cancel import Cancel
from ov.agent.instances import graph
from ov.agent.integrations import datadog, pagerduty

DEFAULT_RANGE = "24h"
SECONDS_PER_DAY = 86_400
FAILED_PROCESS_STATUSES = "3, 14, 21"
FAILED_PROCESS_TYPES_SHOWN = 20
FAILURE_TIMES_SHOWN = 500
UTC_OFFSET_SQL = "select round((sysdate - cast(sys_extract_utc(systimestamp) as date)) * 1440) m from dual"


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


@route("GET", "/api/datadog/databases/discover")
def datadog_discover_databases(_: Handler) -> dict[str, Any]:
    return datadog.discover_databases()


@route("PUT", "/api/datadog/databases")
def datadog_pick_databases(h: Handler) -> dict[str, Any]:
    databases = h.json().get("databases")
    if not isinstance(databases, dict) or not all(isinstance(v, list) for v in databases.values()):
        raise HttpError(400, "Give databases as an object of instance alias to a list of database ids.")
    return datadog.save_databases({str(k): [str(i) for i in v] for k, v in databases.items()})


def _failed_runs(alias: str, start: int, end: int) -> dict[str, Any]:
    sql = graph.SqlReader(alias, Cancel())
    days = round((end - start) / 1000 / SECONDS_PER_DAY, 4)
    failed = (
        "from process p join process_type t on t.process_type_id = p.process_type_id "
        f"where p.status_id in ({FAILED_PROCESS_STATUSES}) and p.submission_date > sysdate - {days}"
    )

    queries = {
        "byType": (
            "select t.process_type, count(*) n, to_char(max(p.submission_date), 'YYYY-MM-DD HH24:MI') last_at "
            f"{failed} group by t.process_type order by n desc",
            FAILED_PROCESS_TYPES_SHOWN,
        ),
        "times": (
            f"select t.process_type, to_char(p.submission_date, 'YYYY-MM-DD\"T\"HH24:MI:SS') at {failed} "
            "order by p.submission_date desc",
            FAILURE_TIMES_SHOWN,
        ),
        "offset": (UTC_OFFSET_SQL, 1),
    }

    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = {name: pool.submit(sql.page, query, 0, size) for name, (query, size) in queries.items()}
        found = {name: future.result() for name, future in futures.items()}

    by_type, times = found["byType"], found["times"]
    offset = int(found["offset"][0]["M"])

    return {
        "byType": [{"type": r["PROCESS_TYPE"], "count": int(r["N"]), "last": r["LAST_AT"]} for r in by_type],
        "failures": [{"type": r["PROCESS_TYPE"], "at": r["AT"]} for r in times],
        "utcOffsetMinutes": offset,
    }


def _incidents(alias: str, start: int, end: int, range_key: str) -> dict[str, Any]:
    report = pagerduty.health(alias, start, end, range_key)
    if report is None:
        raise datadog.Unavailable("PagerDuty is not connected.")
    return report


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
        if section == "onevizion":
            return _failed_runs(alias, start, end)
        if section == "incidents":
            return _incidents(alias, start, end, range_key)
        return datadog.health_section(alias, range_key, section, end)
    except (datadog.Unavailable, graph.NoAccess) as exc:
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
