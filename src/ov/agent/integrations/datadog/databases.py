from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from ov.agent.instances.ovproc import find_instance
from ov.agent.integrations.datadog.connection import DatadogError, connected, database_cache, permissions
from ov.agent.integrations.datadog.hosts import (
    filter_for,
    hosts_in,
    instance_label,
    main_instances,
    owner_of_parts,
    picked_databases,
)
from ov.agent.integrations.datadog.queries import parallel, query_metric, tag_of
from ov.agent.storage.db import now_ms

DATABASE_LOOKBACK_SECONDS = 3600
RDS_TAG = "dbinstanceidentifier"
RDS_ENGINE_TAG = "engine"
ORACLE_TAG = "server"
ORACLE_HOST_TAG = "ddagenthostname"
ORACLE_ENGINE = "oracle"
RDS_ENDPOINT_SUFFIX = ".rds.amazonaws.com"
ORACLE_PROBE = "avg:oracle.session_count{*} by {server,ddagenthostname}"
CATALOG_KEY = "catalog"
RDS_PROBE = "avg:aws.rds.cpuutilization{*} by {dbinstanceidentifier,engine}"


def database_id(server: str) -> str:
    name = server.lower()
    return name.split(".")[0] if name.endswith(RDS_ENDPOINT_SUFFIX) else name


def _database_owner(alias: str, scope: str) -> Callable[[str], bool]:
    found = find_instance(alias)
    if found is None:
        raise DatadogError(f"No signed-in instance matches {alias}.")

    by_label = {instance_label(i["host"]): i["alias"] for i in main_instances()}
    mine = by_label.get(instance_label(found["host"]))
    host_labels = {part for host in hosts_in(scope) or [] for part in host.lower().split(".")[1:]}
    return lambda ident: ident in host_labels or (mine is not None and owner_of_parts([ident], by_label) == mine)


def _probes(jobs: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    end = now_ms()
    start = end - DATABASE_LOOKBACK_SECONDS * 1000
    return parallel({name: partial(query_metric, query, start, end) for name, query in jobs.items()})


def _merge_databases(
    oracle: list[dict[str, Any]], rds: list[dict[str, Any]], keep: Callable[[str], bool]
) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for server in sorted({tag_of(s, ORACLE_TAG) for s in oracle} - {None}):
        found[database_id(server)] = {"id": database_id(server), "engine": ORACLE_ENGINE, "endpoint": server.lower()}

    for series in rds:
        ident = (tag_of(series, RDS_TAG) or "").lower()
        if not ident or (ident not in found and not keep(ident)):
            continue

        engine = tag_of(series, RDS_ENGINE_TAG) or found.get(ident, {}).get("engine", "")
        found[ident] = {**found.get(ident, {"id": ident, "endpoint": ""}), "engine": engine}

    return found


def database_catalog() -> list[dict[str, Any]]:
    cached = database_cache.get(CATALOG_KEY)
    if cached is not None:
        return cached

    return _catalog_of(_probes({"rds": RDS_PROBE, "oracle": ORACLE_PROBE}))


def _catalog_of(probes: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    found = _merge_databases(probes["oracle"], probes["rds"], lambda _: True)
    catalog = [found[k] for k in sorted(found)]
    database_cache.put(CATALOG_KEY, catalog)
    return catalog


def _detected(alias: str, scope: str, probes: dict[str, list[dict[str, Any]]]) -> list[str]:
    agents = {h.lower() for h in hosts_in(scope) or []}
    if not agents:
        return []

    oracle = [s for s in probes["oracle"] if (tag_of(s, ORACLE_HOST_TAG) or "").lower() in agents]
    return sorted(_merge_databases(oracle, probes["rds"], _database_owner(alias, scope)))


def discover_databases(matches: dict[str, str]) -> dict[str, Any]:
    probes = _probes({"rds": RDS_PROBE, "oracle": ORACLE_PROBE})
    groups = {i["alias"]: _detected(i["alias"], matches.get(i["alias"], ""), probes) for i in main_instances()}
    return {"databases": _catalog_of(probes), "groups": {alias: ids for alias, ids in groups.items() if ids}}


def _picked(ids: list[str]) -> dict[str, dict[str, Any]]:
    catalog = {db["id"]: db for db in database_catalog()}
    return {i: catalog.get(i, {"id": i, "engine": "", "endpoint": ""}) for i in ids}


def databases_for(alias: str) -> list[dict[str, Any]]:
    picked = picked_databases(alias)
    if not picked:
        return []

    scope = filter_for(alias)
    key = (alias, scope, tuple(picked))
    cached = database_cache.get(key)
    if cached is not None:
        return cached

    owns = _database_owner(alias, scope)
    found = _picked(picked)
    rows = [{**found[k], "shared": not owns(k)} for k in sorted(found)]
    database_cache.put(key, rows)
    return rows


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
