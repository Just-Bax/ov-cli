from __future__ import annotations

import datetime

from . import datadog, skills, sources
from .ovproc import instances
from .tools import TOOL_GROUPS, tool_specs

NO_INSTANCE = (
    "not chosen. Work it out from context (a case's C_WEBSITE, a host or name in the "
    "message); if it is still unclear, ask the user which instance with ask_user"
)


def system_prompt(write_access: bool, instance: str) -> str:
    today = datetime.date.today().isoformat()
    signed_in = "\n".join(
        f"- {i['alias']}: {i['url']}{' (session expired)' if not i['valid'] else ''}"
        for i in instances()
    )
    configured = "\n".join(
        f"- {s['name']}: {s['description'] or 'no description'}"
        for s in sources.list_sources()
        if s["ready"]
    )
    linked = datadog.connected()
    # The Datadog skill only makes sense when its tools are offered.
    shown = [s for s in skills.enabled_skills() if s["name"] != "datadog" or linked]
    skill_text = "\n\n".join(f"## {s['title']}\n\n{s['content']}" for s in shown)
    offered = {spec["function"]["name"] for spec in tool_specs()}
    groups = "\n".join(
        f"- {title} ({about}): {', '.join(n for n in names if n in offered)}"
        for title, about, names in TOOL_GROUPS
        if any(n in offered for n in names)
    )
    if linked:
        matches = datadog.load_state().get("matches") or {}
        matched = "\n".join(f"- {alias}: {scope}" for alias, scope in sorted(matches.items()))
        dd_text = f"connected. Instance filters:\n{matched or 'none matched yet'}"
    else:
        dd_text = "not connected"

    return f"""You are OV Agent, a senior OneVizion Tier 3 engineer (TCE). You troubleshoot \
support cases and answer questions about OneVizion instances by investigating them yourself \
through the ov CLI. Today is {today}.

Rules that always apply:
- Every claim is backed by something you looked at with a tool. If you could not verify it, say so.
- Changes are blocked unless the user turned on write access for this run; then each change \
waits for their approval. Write access is currently {"ON" if write_access else "OFF"}.
- Never read or print stored credentials, passwords or tokens.
- ASCII only. No em dashes.

Instance for this run: {instance or NO_INSTANCE}

Signed-in instances:
{signed_in or "none"}

# Tools by group

{groups}

Sources you can search with source_search and source_read:
{configured or "none configured"}

Datadog: {dd_text}

# Skills

{skill_text or "No skills enabled."}"""
