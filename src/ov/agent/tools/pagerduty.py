from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ov.agent.integrations import datadog, pagerduty
from ov.agent.tools.base import (
    LABEL_CHARS,
    Handler,
    Tool,
    ToolContext,
    ToolError,
    approved,
    clip,
    int_param,
    raising_tool_errors,
    string_param,
    strings_param,
)
from ov.agent.tools.datadog import WINDOW_FROM, WINDOW_TO

DEFAULT_INCIDENTS = 25
ONCALL_LOOKBACK_DAYS = 30

AREA_OF_TOOL = {
    "pd_incidents": "incidents",
    "pd_incident": "incidents",
    "pd_oncall": "oncall",
    "pd_directory": "incidents",
}

INCIDENT = string_param("Incident number (e.g. 12345), id or PagerDuty link")
CHANGE_GATE = "Only with changes allowed; asks the user first unless the thread is on Auto."


def _pagerduty(handler: Handler) -> Handler:
    return raising_tool_errors(handler, pagerduty.PagerDutyError, datadog.DatadogError)


def _incident_line(i: dict[str, Any]) -> str:
    who = f", assigned {', '.join(i['assignees'])}" if i["assignees"] else ""
    pri = f" {i['priority']}" if i["priority"] else ""
    return (
        f"#{i['number']} [{i['status']}, {i['urgency']}{pri}] {i['title']}\n"
        f"  service {i['service']}, created {pagerduty.short_time(i['created'])} UTC, "
        f"last change {pagerduty.short_time(i['changed'])}{who}\n  {i['url']}"
    )


def _pagerduty_rows(args: dict[str, Any], ctx: ToolContext, default: str) -> tuple[str, list]:
    alias = "" if args.get("all_instances") else pagerduty.resolve_host(args.get("instance"), ctx.instance)
    start = datadog.to_ms(args.get("from"), default)
    end = datadog.to_ms(args.get("to"), "now")
    statuses = [s for s in (args.get("statuses") or []) if s in ("triggered", "acknowledged", "resolved")]
    rows = pagerduty.incidents(start, end, statuses or None)
    if alias:
        rows = pagerduty.for_instance(rows, alias)

    found = pagerduty.find_instance(alias) if alias else None
    where = found["host"] if found else "all instances"
    head = f"PagerDuty incidents for {where}, {pagerduty.iso_utc(start)} to {pagerduty.iso_utc(end)}"
    if statuses:
        head += f", status {'/'.join(statuses)}"
    return head, rows


def _pagerduty_incidents(args: dict[str, Any], ctx: ToolContext) -> str:
    head, rows = _pagerduty_rows(args, ctx, "now-7d")
    text = str(args.get("query") or "").strip().lower()
    if text:
        rows = [r for r in rows if text in f"{r['title']} {r['service']} {r['text']}".lower()]
        head += f", matching {text!r}"
    if not rows:
        return f"{head}\nNone."

    limit = max(1, min(int(args.get("limit") or DEFAULT_INCIDENTS), pagerduty.MAX_INCIDENTS))
    more = f"\n({len(rows) - limit} more not shown)" if len(rows) > limit else ""
    body = "\n".join(_incident_line(r) for r in rows[:limit])
    return clip(f"{head}\n{body}{more}", ctx, "incidents")


def _alert_lines(alerts: list[dict[str, Any]]) -> list[str]:
    lines = ["", "Alerts:"]
    for a in alerts:
        lines.append(f"- {pagerduty.short_time(a['time'])} [{a['status']}] {a['summary']}")
        if a["details"]:
            lines.append("  " + a["details"].replace("\n", "\n  "))
    return lines


def _pagerduty_incident(args: dict[str, Any], ctx: ToolContext) -> str:
    i = pagerduty.incident_detail(str(args["incident"]))
    lines = [_incident_line(i), "", "Timeline:"]
    lines += [f"- {pagerduty.short_time(e['time'])} {e['type']}: {e['summary']}" for e in i["timeline"]] or ["- none"]
    if i["alerts"]:
        lines += _alert_lines(i["alerts"])
    if i["notes"]:
        lines += ["", "Notes:"]
        lines += [f"- {pagerduty.short_time(n['time'])} {n['by']}: {n['text']}" for n in i["notes"]]
    return clip("\n".join(lines), ctx, "incident")


def _instance_policies(alias: str) -> list[str]:
    end = int(time.time() * 1000)
    rows = pagerduty.for_instance(pagerduty.incidents(end - ONCALL_LOOKBACK_DAYS * pagerduty.DAY_MS, end), alias)
    return [r["policy"] for r in rows if r["policy"]]


def _pagerduty_oncall(args: dict[str, Any], ctx: ToolContext) -> str:
    alias = pagerduty.resolve_host(args.get("instance"), ctx.instance)
    at = datadog.to_ms(args.get("at"), "now") if args.get("at") else None
    policies: list[str] = []
    where = "every escalation policy"
    if alias:
        policies = _instance_policies(alias)
        found = pagerduty.find_instance(alias)
        where = found["host"] if found else alias
        if not policies:
            return (
                f"No PagerDuty incident for {where} in the last {ONCALL_LOOKBACK_DAYS} days, so no escalation "
                "policy is known for it. Call again without instance for everyone on call."
            )

    rows = pagerduty.oncall(policies, at)
    if not rows:
        return f"Nobody is on call for {where}."

    lines = [
        f"- level {r['level']} {r['user']} ({r['policy']}"
        f"{', ' + r['schedule'] if r['schedule'] else ''}"
        f"{', until ' + pagerduty.short_time(r['until']) if r['until'] else ''})"
        for r in rows
    ]
    when = f"at {pagerduty.iso_utc(at)}" if at else "now"
    return f"On call {when} for {where}:\n" + "\n".join(lines)


def _pagerduty_label(kind: str) -> Callable[[dict[str, Any]], str]:
    def label(a: dict[str, Any]) -> str:
        what = a.get("incident") or a.get("query") or ""
        at = f" @ {a['instance']}" if a.get("instance") else ""
        return f"PagerDuty {kind}{': ' + str(what)[:LABEL_CHARS] if what else ''}{at}"

    return label


def _pd_change(what: str, apply: Callable[[], dict[str, Any]], ref: str, ctx: ToolContext) -> str:
    if not ctx.can_write():
        raise ToolError(
            "Blocked: changes are OFF for this run. Do not retry. Tell the user what you would do in "
            "PagerDuty; they can switch the thread from Read-only to Ask first or Auto below the chat if they "
            "want you to."
        )

    found = pagerduty.describe(ref)
    if not approved(ctx, f"{what} in PagerDuty?", _incident_line(found)):
        raise ToolError("The user rejected this change. Do not retry it.")
    if not ctx.can_write():
        raise ToolError("Changes were turned off before this was applied.")

    updated = apply()
    return f"Done: {what}.\n{_incident_line(updated)}"


def _pd_note(args: dict[str, Any], ctx: ToolContext) -> str:
    ref, text = str(args["incident"]), str(args["note"])
    return _pd_change(f'Add a note to {ref}: "{text}"', lambda: pagerduty.add_note(ref, text), ref, ctx)


def _pd_ack(args: dict[str, Any], ctx: ToolContext) -> str:
    ref = str(args["incident"])
    return _pd_change(f"Acknowledge {ref}", lambda: pagerduty.set_status(ref, "acknowledged"), ref, ctx)


def _pd_resolve(args: dict[str, Any], ctx: ToolContext) -> str:
    ref = str(args["incident"])
    return _pd_change(f"Resolve {ref}", lambda: pagerduty.set_status(ref, "resolved"), ref, ctx)


def _pd_escalate(args: dict[str, Any], ctx: ToolContext) -> str:
    ref, level = str(args["incident"]), int(args["level"])
    return _pd_change(f"Escalate {ref} to level {level}", lambda: pagerduty.escalate(ref, level), ref, ctx)


def _pd_reassign(args: dict[str, Any], ctx: ToolContext) -> str:
    ref = str(args["incident"])
    if args.get("policy"):
        policy = pagerduty.find_one("policy", str(args["policy"]))
        return _pd_change(
            f"Reassign {ref} to escalation policy {policy['name']}",
            lambda: pagerduty.reassign(ref, policy["id"], []),
            ref,
            ctx,
        )

    people = [pagerduty.find_one("user", str(u)) for u in args.get("users") or []]
    names = ", ".join(u["name"] for u in people)
    return _pd_change(
        f"Reassign {ref} to {names or 'nobody'}",
        lambda: pagerduty.reassign(ref, None, [u["id"] for u in people]),
        ref,
        ctx,
    )


def _pd_snooze(args: dict[str, Any], ctx: ToolContext) -> str:
    ref, minutes = str(args["incident"]), int(args["minutes"])
    return _pd_change(f"Snooze {ref} for {minutes} minutes", lambda: pagerduty.snooze(ref, minutes), ref, ctx)


def _pd_directory(args: dict[str, Any], ctx: ToolContext) -> str:
    query = str(args.get("query") or "")
    found_policies = pagerduty.policies(query)
    found_users = pagerduty.users(query) if query else []
    lines = ["Escalation policies:"] + ([f"- {p['name']} ({p['id']})" for p in found_policies] or ["- none"])
    if query:
        lines += ["", "Users:"] + ([f"- {u['name']} <{u['email']}> ({u['id']})" for u in found_users] or ["- none"])
    return clip("\n".join(lines), ctx, "directory")


READ_TOOLS = [
    Tool(
        "pd_incidents",
        "List PagerDuty incidents for an instance in a time window, newest first: number, "
        "status, urgency, title, service, assignee and link. Incidents are tied to an instance "
        "by the website in their alert (OV monitoring's website field, or the host named in a "
        "Datadog alert). Filter by statuses and a text query; all_instances=true lists all.",
        {
            "instance": string_param("Instance alias or host. Defaults to the run's instance."),
            "from": WINDOW_FROM,
            "to": WINDOW_TO,
            "statuses": {
                "type": "array",
                "items": {"type": "string", "enum": ["triggered", "acknowledged", "resolved"]},
            },
            "query": string_param("Text the title, service or alert details must contain"),
            "all_instances": {"type": "boolean"},
            "limit": int_param(f"Max incidents, default 25, max {pagerduty.MAX_INCIDENTS}"),
        },
        [],
        _pagerduty_label("incidents"),
        _pagerduty(_pagerduty_incidents),
    ),
    Tool(
        "pd_incident",
        "Read one PagerDuty incident in full: status, timeline (triggered, acknowledged, "
        "escalated, resolved), alerts with their details (Datadog monitor alerts carry the "
        "monitor and its query) and notes.",
        {"incident": INCIDENT},
        ["incident"],
        _pagerduty_label("incident"),
        _pagerduty(_pagerduty_incident),
    ),
    Tool(
        "pd_oncall",
        "Who is on call, now or at a given time, by escalation level: for the escalation "
        "policies that paged about an instance in the last 30 days, or for every policy when "
        "no instance is given.",
        {
            "instance": string_param("Instance alias or host; omit for every policy"),
            "at": string_param('A time, e.g. "now-2h" or an ISO time (UTC); default now'),
        },
        [],
        _pagerduty_label("on call"),
        _pagerduty(_pagerduty_oncall),
    ),
    Tool(
        "pd_directory",
        "Find PagerDuty escalation policies, and with a query also users, by name: their ids for "
        "pd_reassign. Without a query lists every policy.",
        {"query": string_param("Part of a policy or user name, or an email")},
        [],
        _pagerduty_label("directory"),
        _pagerduty(_pd_directory),
    ),
]

WRITE_TOOLS = [
    Tool(
        "pd_note",
        f"Add a note to a PagerDuty incident. {CHANGE_GATE}",
        {"incident": INCIDENT, "note": string_param("Note text")},
        ["incident", "note"],
        _pagerduty_label("note"),
        _pagerduty(_pd_note),
    ),
    Tool(
        "pd_ack",
        f"Acknowledge a PagerDuty incident. {CHANGE_GATE}",
        {"incident": INCIDENT},
        ["incident"],
        _pagerduty_label("acknowledge"),
        _pagerduty(_pd_ack),
    ),
    Tool(
        "pd_resolve",
        f"Resolve a PagerDuty incident. {CHANGE_GATE} Add a note with the cause first.",
        {"incident": INCIDENT},
        ["incident"],
        _pagerduty_label("resolve"),
        _pagerduty(_pd_resolve),
    ),
    Tool(
        "pd_escalate",
        "Escalate a PagerDuty incident to a level of its escalation policy (pd_oncall shows the levels). "
        "Only with changes allowed; asks the user first unless the thread is on Auto.",
        {"incident": INCIDENT, "level": int_param("Escalation level, 1 or higher")},
        ["incident", "level"],
        _pagerduty_label("escalate"),
        _pagerduty(_pd_escalate),
    ),
    Tool(
        "pd_reassign",
        "Reassign a PagerDuty incident to another escalation policy, or to users. Names are looked "
        "up like pd_directory and must match one. Only with changes allowed; asks the user first unless "
        "the thread is on Auto.",
        {
            "incident": INCIDENT,
            "policy": string_param("Escalation policy name or id"),
            "users": strings_param("User names, emails or ids, instead of a policy"),
        },
        ["incident"],
        _pagerduty_label("reassign"),
        _pagerduty(_pd_reassign),
    ),
    Tool(
        "pd_snooze",
        f"Snooze an acknowledged PagerDuty incident. {CHANGE_GATE}",
        {"incident": INCIDENT, "minutes": int_param("Minutes, 1 to 1440")},
        ["incident", "minutes"],
        _pagerduty_label("snooze"),
        _pagerduty(_pd_snooze),
    ),
]


def offered_readers() -> list[Tool]:
    if not pagerduty.connected():
        return []
    areas = pagerduty.permissions()
    return [t for t in READ_TOOLS if areas[AREA_OF_TOOL[t.name]]]


def offered_writers(write: bool) -> list[Tool]:
    allowed = write and pagerduty.connected() and pagerduty.permissions()["incidents"]
    return WRITE_TOOLS if allowed else []
