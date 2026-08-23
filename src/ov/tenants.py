from __future__ import annotations

import json
import re
from typing import Any

from .errors import Ambiguous, NotFound, OvError

# Switching tenants is a web session operation: it swaps which user the session
# is authenticated as. There is no API for it, and no way to pick a tenant at
# the login step.
SWITCH_PATH = "/program/FormProg.do"
DEFAULT_PATH = "/Default.do"

# The only place the tenant list is exposed. Default.jsp writes it into the page
# as JSON, and only when the account exists in more than one tenant; a
# single-tenant account gets `var programMenu = null`.
_PROGRAM_MENU = re.compile(r"var\s+programMenu\s*=\s*(null|\{.*?\})\s*;", re.S)

NO_TENANTS = (
    "This account is in one tenant on this instance, so there is nothing to switch to. "
    "A tenant needs a user with your email address before you can reach it."
)


def parse_program_menu(page: str) -> dict[str, str]:
    """Pull {pid: name} out of a rendered Default.do."""
    match = _PROGRAM_MENU.search(page or "")
    if not match:
        return {}
    raw = match.group(1)
    if raw == "null":
        return {}
    try:
        menu = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(menu, dict):
        return {}
    return {str(pid): str(name) for pid, name in menu.items() if name}


def resolve_tenant(tenants: dict[str, str], ref: str) -> tuple[str, str]:
    """Turn a tenant name, id or unambiguous prefix into (pid, name)."""
    needle = (ref or "").strip()
    if not needle:
        raise NotFound("No tenant given.")
    if not tenants:
        raise OvError(NO_TENANTS)

    if needle in tenants:
        return needle, tenants[needle]

    lowered = needle.lower()
    exact = [(p, n) for p, n in tenants.items() if n.lower() == lowered]
    if len(exact) == 1:
        return exact[0]

    partial = [(p, n) for p, n in tenants.items() if n.lower().startswith(lowered)]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        listed = "\n".join(f"  {n}  (pid {p})" for p, n in sorted(partial, key=lambda x: x[1]))
        raise Ambiguous(f"{ref!r} matches {len(partial)} tenants:\n{listed}")

    known = ", ".join(sorted(tenants.values()))
    raise NotFound(f"No tenant matches {ref!r}. Available: {known}.")


def tenant_rows(tenants: dict[str, str], current_id: str = "") -> list[dict[str, Any]]:
    return [
        {"tenant_id": pid, "name": name, "current": pid == current_id}
        for pid, name in sorted(tenants.items(), key=lambda x: x[1].lower())
    ]
