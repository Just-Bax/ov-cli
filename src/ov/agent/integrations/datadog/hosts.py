from __future__ import annotations

import re
from typing import Any

from ov.agent.instances.ovproc import find_instance, host_of, instances
from ov.agent.integrations.datadog.connection import Client, DatadogError, client, field, load_state, permissions

HOSTS_PAGE = 1000

_HOSTS = re.compile(r"^host:\(([^()]+)\)$")
_ONE_HOST = re.compile(r"^host:([^\s*()]+)$")


def _instance_entry(table: dict[str, Any], alias: str) -> Any:
    if alias in table:
        return table[alias]

    found = find_instance(alias)
    if found is None:
        raise DatadogError(f"No signed-in instance matches {alias}.")

    tenants_last = sorted(
        (i for i in instances() if i["host"] == found["host"] and i["alias"] in table),
        key=lambda i: bool(i["tenant"]),
    )
    return table[tenants_last[0]["alias"]] if tenants_last else None


def filter_for(alias: str) -> str:
    return _instance_entry(load_state().get("matches", {}), alias) or ""


def picked_databases(alias: str) -> list[str]:
    return _instance_entry(load_state().get("databases", {}), alias) or []


def hosts_in(scope: str) -> list[str] | None:
    text = scope.strip()
    many = _HOSTS.match(text)
    if many:
        return [h.strip() for h in many.group(1).split(" OR ") if h.strip()]
    one = _ONE_HOST.match(text)
    return [one.group(1)] if one else None


def scope_of(hosts: list[str]) -> str:
    hosts = sorted(dict.fromkeys(h.strip() for h in hosts if h.strip()))
    if not hosts:
        return ""
    return f"host:{hosts[0]}" if len(hosts) == 1 else f"host:({' OR '.join(hosts)})"


def role_of(host: str) -> str:
    first = host.split(".")[0].lower()
    words: list[str] = []
    for part in re.split(r"[-_]", first):
        if part.isalpha():
            words.append(part)
            continue

        leading_letters = re.sub(r"[^a-z].*", "", part)
        if leading_letters and not words:
            words.append(leading_letters)
        break

    return "-".join(words) or first


def with_role(scope: str, role: str | None) -> str:
    if not role or role == "all":
        return scope

    hosts = hosts_in(scope)
    if hosts is None:
        raise DatadogError("This instance's Datadog filter is not a list of servers, so it has no roles.")

    picked = [h for h in hosts if role_of(h) == role.lower()]
    if not picked:
        roles = ", ".join(sorted({role_of(h) for h in hosts}))
        raise DatadogError(f"No {role} servers. This instance has: {roles}.")

    return scope_of(picked)


def instance_label(website: str) -> str:
    return website.split(":")[0].split(".")[0].lower()


def owner_of_parts(parts: list[str], instances_by_label: dict[str, str]) -> str | None:
    owners = [
        (label, alias)
        for label, alias in instances_by_label.items()
        if any(p == label or p.startswith(label + "-") for p in parts)
    ]
    return max(owners, key=lambda owner: len(owner[0]))[1] if owners else None


def owner_of(host: str, instances_by_label: dict[str, str], websites: dict[str, str]) -> str | None:
    name = host.lower()
    if name in websites:
        return websites[name]
    return owner_of_parts(name.split(".")[1:], instances_by_label)


def _all_hosts(dd: Client) -> list[str]:
    if not permissions()["hosts"]:
        raise DatadogError("Finding servers needs the hosts_read scope on the application key.")

    names: list[str] = []
    while True:
        data = dd.call("GET", "/api/v1/hosts", "hosts", params={"count": HOSTS_PAGE, "start": len(names)})
        rows = field(data, "host_list")
        names += [row["name"] for row in rows]
        if not rows or len(names) >= field(data, "total_matching"):
            return sorted(set(names))


def main_instances() -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for inst in sorted(instances(), key=lambda i: bool(i["tenant"])):
        seen.setdefault(inst["host"], inst)
    return list(seen.values())


def discover() -> dict[str, Any]:
    with client() as dd:
        names = _all_hosts(dd)

    mains = main_instances()
    by_label = {instance_label(i["host"]): i["alias"] for i in mains}
    websites = {i["host"].split(":")[0].lower(): i["alias"] for i in mains}
    hosts = []
    groups: dict[str, list[str]] = {}
    for name in names:
        alias = owner_of(name, by_label, websites)
        hosts.append({"name": name, "role": role_of(name), "alias": alias})
        if alias:
            groups.setdefault(alias, []).append(name)

    return {"hosts": hosts, "groups": {k: scope_of(v) for k, v in groups.items()}}


def resolve_scope(instance: str | None, current: str, role: str | None = None) -> tuple[str, str]:
    target = (instance or current).strip()
    if not target:
        return "", ""

    found = find_instance(target)
    if found is None:
        return host_of(target), ""

    scope = filter_for(found["alias"])
    if not scope:
        raise DatadogError(
            f"{found['host']} is not matched to Datadog yet. Match it in Settings > "
            "Integrations > Datadog, or pass a query with its host or service tag."
        )

    return found["alias"], with_role(scope, role)
