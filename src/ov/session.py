from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from . import store
from .errors import Ambiguous, NotFound, NotLoggedIn

SESSION_COOKIE = "JSESSIONID"

# Re-mint this far ahead of the recorded expiry rather than waiting for a 401,
# so a long-running command does not fail halfway through a page loop.
REFRESH_MARGIN_SECONDS = 300

# The server reports the expiry as naive local time in its own timezone, so a
# value outside this range means we read it wrong and should not trust it.
MIN_PLAUSIBLE_TTL = 60
MAX_PLAUSIBLE_TTL = 7 * 24 * 3600
ASSUMED_TTL_SECONDS = 900

_UNSAFE_ALIAS = re.compile(r"[^a-z0-9._-]+")


@dataclass
class Session:
    """What the CLI needs to speak to one instance as one user.

    Two credentials, deliberately: the cookies authenticate the web UI (which is
    what mints tokens and serves the OpenAPI schema), and the bearer token is the
    only thing /api/v3 accepts. Session mode holds both; token mode holds only
    the bearer.
    """

    base_url: str
    alias: str = ""
    mode: str = "session"
    tenant: str = ""
    tenant_id: str = ""
    cookies: dict[str, str] = field(default_factory=dict)
    bearer_token: str = ""
    expires_at: float = 0.0
    expires_text: str = ""
    saved_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.alias:
            self.alias = default_alias(self.base_url, self.tenant)

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).netloc

    @property
    def access_key(self) -> str:
        return self.bearer_token.partition(":")[0]

    @property
    def is_static(self) -> bool:
        """Token mode has no cookies, so nothing can be re-minted without the user."""
        return self.mode == "token"

    def seconds_left(self) -> float | None:
        if not self.expires_at:
            return None
        return self.expires_at - time.time()

    def needs_refresh(self) -> bool:
        if self.is_static or not self.cookies:
            return False
        if not self.bearer_token:
            return True
        left = self.seconds_left()
        return left is not None and left < REFRESH_MARGIN_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "alias": self.alias,
            "mode": self.mode,
            "tenant": self.tenant,
            "tenant_id": self.tenant_id,
            "cookies": self.cookies,
            "bearer_token": self.bearer_token,
            "expires_at": self.expires_at,
            "expires_text": self.expires_text,
            "saved_at": self.saved_at,
        }

    def redacted(self) -> dict[str, Any]:
        left = self.seconds_left()
        return {
            "alias": self.alias,
            "base_url": self.base_url,
            "tenant": self.tenant or None,
            "mode": self.mode,
            "access_key": self.access_key,
            "expires": self.expires_text or None,
            "seconds_left": round(left) if left is not None else None,
        }


def default_alias(base_url: str, tenant: str = "") -> str:
    """Name a connection after its hostname, and its tenant when it has one.

    https://acme.onevizion.com -> acme; its mTRAC tenant -> acme/mtrac. A bare
    host alias keeps meaning the tenant the account signs in to, as it did
    before tenants existed.
    """
    host = urlsplit(base_url).hostname or base_url
    label = _slug(host.split(".")[0]) or "default"
    return f"{label}/{_slug(tenant)}" if tenant else label


def _slug(value: str) -> str:
    return _UNSAFE_ALIAS.sub("-", (value or "").lower()).strip("-")


def host_alias(base_url: str, tenant: str = "") -> str:
    host = urlsplit(base_url).hostname or base_url
    label = _slug(host) or "default"
    return f"{label}/{_slug(tenant)}" if tenant else label


def _from_dict(data: dict[str, Any], alias: str = "") -> Session:
    cookies = data.get("cookies")
    return Session(
        base_url=data.get("base_url") or "",
        alias=data.get("alias") or alias,
        mode=data.get("mode") or "session",
        tenant=data.get("tenant") or "",
        tenant_id=str(data.get("tenant_id") or ""),
        cookies=cookies if isinstance(cookies, dict) else {},
        bearer_token=data.get("bearer_token") or "",
        expires_at=float(data.get("expires_at") or 0),
        expires_text=data.get("expires_text") or "",
        saved_at=float(data.get("saved_at") or 0),
    )


def _read_all() -> dict[str, Session]:
    data = store.read()
    raw = data.get(store.SESSIONS_KEY)
    sessions = {}
    if isinstance(raw, dict):
        for alias, entry in raw.items():
            if isinstance(entry, dict) and entry.get("base_url"):
                sessions[alias] = _from_dict(entry, alias)
    return sessions


def all_sessions() -> dict[str, Session]:
    return _read_all()


def _write_all(sessions: dict[str, Session], current: str | None = None) -> None:
    changes: dict[str, Any] = {
        store.SESSIONS_KEY: {a: s.to_dict() for a, s in sessions.items()} or None
    }
    if current is not None:
        changes[store.CURRENT_KEY] = current or None
    store.update(**changes)


def current_alias() -> str | None:
    sessions = _read_all()
    if not sessions:
        return None
    alias = store.read().get(store.CURRENT_KEY)
    if isinstance(alias, str) and alias in sessions:
        return alias
    # A stale pointer, from a logout that removed the current instance.
    return next(iter(sessions))


def is_same_target(session: Session, base_url: str, tenant_id: str) -> bool:
    """One stored credential per (host, tenant), since that pair is what a
    bearer token is actually scoped to."""
    return session.base_url == base_url.rstrip("/") and session.tenant_id == (tenant_id or "")


def unique_alias(base_url: str, preferred: str = "", tenant: str = "", tenant_id: str = "") -> str:
    """Pick a free alias, keeping the one a connection already owns.

    Two hosts can share a first label ('acme.onevizion.com' and 'acme.eu.dev'),
    so a taken name falls back to the whole host rather than a counter, which
    stays recognisable.
    """
    base_url = base_url.rstrip("/")
    sessions = _read_all()
    for alias, session in sessions.items():
        if is_same_target(session, base_url, tenant_id) and not preferred:
            return alias

    candidate = preferred or default_alias(base_url, tenant)
    taken = sessions.get(candidate)
    if taken is None or is_same_target(taken, base_url, tenant_id):
        return candidate
    if preferred:
        raise Ambiguous(f"Alias {preferred!r} already points at {taken.base_url}.")

    candidate = host_alias(base_url, tenant)
    taken = sessions.get(candidate)
    if taken is None or is_same_target(taken, base_url, tenant_id):
        return candidate

    suffix = 2
    while f"{candidate}-{suffix}" in sessions:
        suffix += 1
    return f"{candidate}-{suffix}"


def resolve(ref: str) -> str:
    """Turn what the user typed into one stored alias.

    Accepts the alias, the full base URL, the hostname, the tenant name, or an
    unambiguous prefix of any of them, so 'ov -i acme', 'ov -i acme.onevizion.com'
    and 'ov -i https://acme.onevizion.com' all land on the same instance, and
    'ov -i mtrac' finds sandbox/mtrac without spelling out the host.
    """
    sessions = _read_all()
    if not sessions:
        raise NotLoggedIn

    needle = ref.strip().rstrip("/")
    if not needle:
        raise NotFound("No instance given.")

    if needle in sessions:
        return needle

    lowered = needle.lower()
    stripped = lowered.split("://", 1)[-1]

    exact = [
        alias
        for alias, session in sessions.items()
        if session.base_url.lower() == lowered
        or session.host.lower() == stripped
        or session.tenant.lower() == lowered
        or alias.rpartition("/")[2] == lowered
    ]
    picked = _prefer_default_tenant(exact, sessions)
    if picked:
        return picked

    partial = [
        alias
        for alias, session in sessions.items()
        if alias.startswith(lowered)
        or session.host.lower().startswith(stripped)
        or session.tenant.lower().startswith(lowered)
        or alias.rpartition("/")[2].startswith(lowered)
    ]
    picked = _prefer_default_tenant(partial, sessions)
    if picked:
        return picked
    if len(partial) > 1:
        listed = "\n".join(f"  {a}  {sessions[a].base_url}" for a in sorted(partial))
        raise Ambiguous(f"{ref!r} matches {len(partial)} instances:\n{listed}")

    known = ", ".join(sorted(sessions)) or "none"
    raise NotFound(f"No instance matches {ref!r}. Signed in to: {known}.")


def _prefer_default_tenant(matches: list[str], sessions: dict[str, Session]) -> str | None:
    """Settle a host signed in to several of its tenants: naming the host
    resolves to the tenant the account signs in to."""
    if len(matches) == 1:
        return matches[0]
    if not matches or len({sessions[a].base_url for a in matches}) != 1:
        return None
    plain = [a for a in matches if not sessions[a].tenant]
    return plain[0] if len(plain) == 1 else None


def save(session: Session, make_current: bool = True) -> Session:
    session.saved_at = time.time()
    sessions = _read_all()

    # Two systems can share a hostname's first label. Only the store knows
    # that, so uniqueness is settled here rather than trusted from the caller.
    taken = sessions.get(session.alias)
    if taken is not None and not is_same_target(taken, session.base_url, session.tenant_id):
        session.alias = unique_alias(session.base_url, tenant=session.tenant,
                                     tenant_id=session.tenant_id)

    sessions[session.alias] = session
    _write_all(sessions, session.alias if make_current else None)
    return session


def load(ref: str | None = None) -> Session:
    """The session for `ref`, or the current instance when nothing is asked for."""
    sessions = _read_all()
    if not sessions:
        raise NotLoggedIn

    alias = resolve(ref) if ref else current_alias()
    if not alias or alias not in sessions:
        raise NotLoggedIn

    session = sessions[alias]
    if not session.bearer_token and not session.cookies:
        raise NotLoggedIn
    return session


def use(ref: str) -> Session:
    alias = resolve(ref)
    sessions = _read_all()
    _write_all(sessions, alias)
    return sessions[alias]


def exists(ref: str | None = None) -> bool:
    try:
        load(ref)
    except (NotLoggedIn, NotFound, Ambiguous):
        return False
    return True


def remove(ref: str) -> Session:
    alias = resolve(ref)
    sessions = _read_all()
    removed = sessions.pop(alias)
    remaining = next(iter(sessions), "")
    _write_all(sessions, remaining)
    return removed


def clear() -> int:
    count = len(_read_all())
    _write_all({}, "")
    return count


def expiry_to_epoch(text: str) -> float:
    """Turn the server's 'yyyy-MM-ddTHH:mm:ss' into a local deadline.

    It carries no timezone and is stamped in the server's zone, so a wrong guess
    would either expire the token early or trust it past its death. An
    implausible result is replaced by a short fixed TTL; either way a 401 still
    triggers a re-mint, which is what actually keeps this correct.
    """
    if not text:
        return time.time() + ASSUMED_TTL_SECONDS
    try:
        deadline = datetime.fromisoformat(text.strip()).timestamp()
    except ValueError:
        return time.time() + ASSUMED_TTL_SECONDS

    ttl = deadline - time.time()
    if MIN_PLAUSIBLE_TTL <= ttl <= MAX_PLAUSIBLE_TTL:
        return deadline
    return time.time() + ASSUMED_TTL_SECONDS


def cookies_from_playwright(raw: list[dict[str, Any]]) -> dict[str, str]:
    return {c["name"]: c["value"] for c in raw if c.get("name") and c.get("value")}
