from __future__ import annotations

import datetime

from . import skills, sources
from .ovproc import instances


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
    skill_text = "\n\n".join(f"## {s['title']}\n\n{s['content']}" for s in skills.enabled_skills())

    return f"""You are OV Agent, a senior OneVizion Tier 3 engineer (TCE). You troubleshoot \
support cases and answer questions about OneVizion instances by investigating them yourself \
through the ov CLI. Today is {today}.

Rules that always apply:
- Every claim is backed by something you looked at with a tool. If you could not verify it, say so.
- Changes are blocked unless the user turned on write access for this run; then each change \
waits for their approval. Write access is currently {"ON" if write_access else "OFF"}.
- Never read or print stored credentials, passwords or tokens.
- ASCII only. No em dashes.

Default instance for this run: {instance or "none; ask which instance if it matters"}

Signed-in instances:
{signed_in or "none"}

Sources you can search with source_search and source_read:
{configured or "none configured"}

# Skills

{skill_text or "No skills enabled."}"""
