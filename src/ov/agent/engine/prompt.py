from __future__ import annotations

import datetime

from ov.agent import workspace as project
from ov.agent.instances.ovproc import instances
from ov.agent.integrations import datadog, pagerduty
from ov.agent.storage import db
from ov.agent.tools import TOOL_GROUPS, tool_specs
from ov.agent.tools.thread import offered_skills

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


def system_prompt(write_access: bool, instance: str) -> str:
    today = datetime.date.today().isoformat()
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
through the ov CLI. Today is {today}.

Rules that always apply:
- Every claim is backed by something you looked at with a tool. If you could not verify it, say so. \
Label general knowledge you did not check on the instance or in the code as unverified.
- An empty result is not proof that something does not exist or never happened. Say where you looked \
("no rows in X") and try another source before concluding.
- Never call a tool as a placeholder (echo, where 1=0). To just answer, reply without tools.
- Changes are blocked unless the user turned on write access for this run; then each change \
waits for their approval. Write access is currently {"ON" if write_access else "OFF"}.
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
