from __future__ import annotations

import datetime
import re
from typing import Any

from ov.agent import workspace as project
from ov.agent.instances.ovproc import instances
from ov.agent.integrations import datadog, pagerduty
from ov.agent.storage import db
from ov.agent.tools import TOOL_GROUPS, tool_specs
from ov.agent.tools.thread import offered_skills

_SENT = re.compile(r"^\[Sent [^\]]*\]\n\n")
EXPIRED = " (session expired: use it anyway, the user is asked to sign in on the first call)"
NO_INSTANCE = (
    "not chosen. Work it out from context (a case's C_WEBSITE, a host or name in the "
    "message); if it is still unclear, ask the user which instance with run_ask"
)


def _servers(scope: str) -> str:
    hosts = datadog.hosts_in(scope)
    if not hosts:
        return scope

    roles: dict[str, list[str]] = {}
    for host in hosts:
        roles.setdefault(datadog.role_of(host), []).append(host)
    return "; ".join(f"{role}: {', '.join(names)}" for role, names in sorted(roles.items()))


def _workspace_text() -> str:
    if not project.configured():
        return "none set, so there are no ws_ tools. Code work needs the user to pick a folder in Settings > Workspace."
    notes = db.get_preferences()["workspaceNotes"].strip()
    return f"{project.root()}" + (f"\nNotes from the user:\n{notes}" if notes else "")


def _datadog_text() -> str:
    if not datadog.connected():
        return "not connected"
    matches = datadog.load_state().get("matches") or {}
    matched = "\n".join(f"- {alias}: {_servers(scope)}" for alias, scope in sorted(matches.items()))
    return f"connected. Instance filters:\n{matched or 'none matched yet'}"


def _pagerduty_text() -> str:
    if not pagerduty.connected():
        return "not connected"
    return "connected. Incidents are tied to instances by the website in their alert."


def now_text() -> str:
    local = datetime.datetime.now().astimezone()
    utc = local.astimezone(datetime.UTC)
    offset = local.strftime("%z")
    return (
        f"{local:%Y-%m-%d %H:%M} on the user's computer ({local.tzname()}, UTC{offset[:3]}:{offset[3:]}), "
        f"{utc:%Y-%m-%d %H:%M} UTC"
    )


def stamped(content: Any) -> Any:
    stamp = f"[Sent {now_text()}]"
    if isinstance(content, str):
        return f"{stamp}\n\n{_SENT.sub('', content)}"
    first, *rest = content
    return [{**first, "text": f"{stamp}\n\n{_SENT.sub('', first['text'])}"}, *rest]


def system_prompt(write_access: bool, instance: str) -> str:
    signed_in = "\n".join(f"- {i['alias']}: {i['url']}{EXPIRED if not i['valid'] else ''}" for i in instances())
    skills = offered_skills()
    core = "\n\n".join(f"## {s['title']}\n\n{s['content']}" for s in skills if s["core"])
    skill_list = "\n".join(f"- {s['name']}: {s['description'] or s['title']}" for s in skills if not s["core"])
    offered = {spec["function"]["name"] for spec in tool_specs(write_access)}
    groups = "\n".join(
        f"- {title} ({about}): {', '.join(n for n in names if n in offered)}"
        for title, about, names in TOOL_GROUPS
        if any(n in offered for n in names)
    )

    return f"""You are OV Agent, a senior OneVizion Tier 3 engineer (TCE). You troubleshoot \
support cases and answer questions about OneVizion instances by investigating them yourself \
through the ov CLI. Each user message starts with the time it was sent, on the user's computer and \
in UTC. Instances, their databases and Datadog may each run in another time zone; check before \
comparing times.

Rules that always apply:
- When the request names no concrete symptom or outcome ("fix X", "clean up Y", "check Z"), ask with \
run_ask what is wrong or wanted before investigating; you may first list the objects it could mean with \
one or two cheap lookups.
- Every claim is backed by something you looked at with a tool. If you could not verify it, say so. \
Label general knowledge you did not check on the instance or in the code as unverified.
- An empty result is not proof that something does not exist or never happened. Say where you looked \
("no rows in X") and try another source before concluding.
- Never call a tool as a placeholder (echo, where 1=0). To just answer, reply without tools.
- Changes are blocked unless the user turned on Allow changes for this run; even then you change \
only what the user agreed to. Allow changes is currently {"ON" if write_access else "OFF"}.
- When the user wants to see, show, open, check, navigate or test something in the OneVizion web UI, use the \
browser: the user watches it beside the chat. Open it with browser_open, plan the test, then hand each part to \
browser_run as a concrete goal with the expected result; a fast assistant drives the mouse and keyboard and \
reports back with a screenshot. Read every report and its Result line before the next goal. While the browser \
is open, every change happens in the UI; ov, SQL and commands only read, to check results. If the UI cannot \
do a step, such as a read-only field or a missing button, stop and tell the user instead of doing it another way.
- Never read or print stored credentials, passwords or tokens.
- ASCII only. No em dashes.

Instance for this run: {instance or NO_INSTANCE}

Signed-in instances:
{signed_in or "none"}

# Tools by group

{groups}

Workspace: {_workspace_text()}

Datadog: {_datadog_text()}

PagerDuty: {_pagerduty_text()}

# Skills to read when a task needs them

Each is a guide for one area. Before working on a task, read every skill below that covers it with \
skill_read; reviewing an incident, for example, means reading pagerduty and datadog first.

{skill_list or "None."}

# Core skills

These always apply.

{core or "None enabled."}"""
