from __future__ import annotations

import datetime
import re
from typing import Any

from ov.agent import workspace as project
from ov.agent.engine.cases import TRACKOR_HOST, WEBSITE_FIELD
from ov.agent.instances import access as account_access
from ov.agent.instances.ovproc import instances
from ov.agent.integrations import datadog, pagerduty
from ov.agent.storage import db
from ov.agent.storage.models import Access
from ov.agent.tools import TOOL_GROUPS, tool_specs
from ov.agent.tools.thread import offered_skills

_SENT = re.compile(r"^\[Sent [^\]]*\]\n\n")
EXPIRED = " (session expired: the user is asked to sign in when you first use it)"
NO_INSTANCE = (
    f"not chosen. Work it out from context (a case's {WEBSITE_FIELD}, a host or name in the "
    "message); if it is still unclear, ask the user which instance with run_ask"
)
PROFILE_INSTRUCTIONS = (
    "Their standing instructions, for every thread. Follow them unless the user says otherwise in the thread or "
    "they conflict with the rules above:"
)
ACCESS_TEXT = {
    Access.READ: "OFF: read-only",
    Access.ASK: "ON, and each instance, PagerDuty, browser or outside change waits for the user's approval",
    Access.AUTO: "ON, and changes run without asking the user unless they look risky",
    Access.FULL: "ON with full access: every change runs without any check or question",
}


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


def _profile_text() -> str:
    preferences = db.get_preferences()
    name, instructions = preferences["fullName"].strip(), preferences["instructions"].strip()
    parts = [f"Name: {name}"] if name else []
    if instructions:
        parts.append(f"{PROFILE_INSTRUCTIONS}\n{instructions}")
    return f"\n# About the user\n\n{chr(10).join(parts)}\n" if parts else ""


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


def _instance_line(row: dict[str, Any]) -> str:
    expired = EXPIRED if not row["valid"] else ""
    return f"- {row['alias']}: {row['url']}{expired}. {account_access.describe(row['alias'])}"


def system_prompt(access: Access, instance: str) -> str:
    signed_in = "\n".join(_instance_line(i) for i in instances())
    skills = offered_skills()
    core = "\n\n".join(f"## {s['title']}\n\n{s['content']}" for s in skills if s["core"])
    skill_list = "\n".join(f"- {s['name']}: {s['description'] or s['title']}" for s in skills if not s["core"])
    offered = {spec["function"]["name"] for spec in tool_specs(access != Access.READ)}
    groups = "\n".join(
        f"- {title} ({about}): {', '.join(n for n in names if n in offered)}"
        for title, about, names in TOOL_GROUPS
        if any(n in offered for n in names)
    )

    return f"""You are OV Agent, a senior OneVizion engineer. You answer questions about OneVizion \
instances, investigate problems and support cases, and help configure and work with them, by looking at \
the instances yourself through the ov CLI. Each user message starts with the time it was sent, on the \
user's computer and in UTC. Instances, their databases and Datadog may each run in another time zone; \
check before comparing times.

Rules that always apply:
- Ask first, then work. When an input you need is missing or ambiguous (which instance, which object, the \
scope, the outcome wanted, or no concrete symptom as in "fix X" or "check Z"), ask with run_ask before \
running any lookup. Put related questions in one run_ask call, at most 5, each with clear options. Look up \
yourself only facts the user expects you to find.
- Every claim is backed by something you looked at with a tool. If you could not verify it, say so. \
Label general knowledge you did not check on the instance or in the code as unverified.
- An empty result is not proof that something does not exist or never happened. Say where you looked \
("no rows in X") and try another source before concluding.
- Never call a tool as a placeholder (echo, where 1=0). To just answer, reply without tools.
- The user sees only your last message of a turn; your tool calls and earlier notes are folded away. End every \
turn with one message that stands on its own: the answer or result first, then the evidence behind it, what you \
changed or tested and how it went, and what is still open or needs the user. Never end on a tool call or a bare \
"done", and never point back to earlier notes.
- Changes are blocked unless the user allowed them for this run; even then you change only what the \
user agreed to. Changes are currently {ACCESS_TEXT[access]}.
- When the user wants to see, show, open, check, navigate or test something in the OneVizion web UI, use the \
browser: the user watches it beside the chat. Open it with browser_open, plan the test, then hand each part to \
browser_run as a concrete goal with the expected result; a fast assistant drives the mouse and keyboard and \
reports back with a screenshot. Read every report and its Result line before the next goal. While the browser \
is open, every change happens in the UI; ov, SQL and commands only read, to check results. If the UI cannot \
do a step, such as a read-only field or a missing button, stop and tell the user instead of doing it another way.
- User messages can carry mentions the user picked: [name](attachment:<file>) is a file attached to that \
message (open it with run_read), [path](workspace:<path>) a workspace file, or a folder when the path ends \
in /, [name](ov:<type>/<id>) an object of that type and id on the run's instance, [title](thread:<id>) another \
thread (read it with thread_read), and [title](skill:<name>) a skill whose text follows the message. Each \
mention means exactly that object.
- Never read or print stored credentials, passwords or tokens.
- When a task needs an instance or {TRACKOR_HOST} and it is not signed in or its session expired, call the \
tool anyway: the user is asked to sign in. Never skip a step or give up because something is not signed in.
- Each instance below says what this account can use there. Use the sources it allows: Test SQL when it is \
available, otherwise component export, the platform DB source and the API. When a missing privilege limits the \
answer, say which one.
- When the user moves the work to another instance (dev, test, a sandbox), keep using that one for every \
following call until they move again, and pass it as instance on each call. Every link you give points to the \
instance where you found that object, never the run's instance by habit.
- ASCII only. No em dashes.

Instance for this run: {instance or NO_INSTANCE}

Signed-in instances (sign in to any other instance by using it):
{signed_in or "none"}
{_profile_text()}
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
