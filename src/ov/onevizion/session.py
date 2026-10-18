from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from ov.core import credentials, store
from ov.core.errors import Ambiguous, NotFound, NotLoggedIn, OvError
from ov.core.paths import config_file

REFRESH_MARGIN_SECONDS = 300
MIN_PLAUSIBLE_TTL = 60
MAX_PLAUSIBLE_TTL = 7 * 24 * 3600
ASSUMED_TTL_SECONDS = 900

_UNSAFE_ALIAS = re.compile(r"[^a-z0-9._-]+")


@dataclass
class Session:
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
        return self.mode == "token"

    @property
    def credential_key(self) -> str:
        return f"{self.base_url}|{self.tenant_id}"

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
            "expires_at": self.expires_at,
            "expires_text": self.expires_text,
            "saved_at": self.saved_at,
        }

    def secrets(self) -> dict[str, Any]:
        return {"cookies": self.cookies, "bearer_token": self.bearer_token}

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
    return _with_tenant(_slug(_hostname(base_url).split(".")[0]), tenant)


def host_alias(base_url: str, tenant: str = "") -> str:
    return _with_tenant(_slug(_hostname(base_url)), tenant)


def _with_tenant(label: str, tenant: str) -> str:
    return f"{label}/{_slug(tenant)}" if tenant else label


def _hostname(base_url: str) -> str:
    host = urlsplit(base_url).hostname
    if not host:
        raise OvError(f"Not an instance URL: {base_url!r}")
    return host


def _slug(value: str) -> str:
    return _UNSAFE_ALIAS.sub("-", value.lower()).strip("-")


def _from_dict(data: dict[str, Any], alias: str) -> Session:
    try:
        return Session(
            base_url=data["base_url"],
            alias=alias,
            mode=data["mode"],
            tenant=data["tenant"],
            tenant_id=data["tenant_id"],
            expires_at=data["expires_at"],
            expires_text=data["expires_text"],
            saved_at=data["saved_at"],
        )
    except KeyError as exc:
        raise OvError(f"Instance {alias!r} in {config_file()} is missing {exc}.") from exc


def _entries(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = data.get(store.SESSIONS_KEY, {})
    if not isinstance(entries, dict):
        raise OvError(f"'{store.SESSIONS_KEY}' in {config_file()} is not a JSON object.")
    return entries


def _read_all() -> dict[str, Session]:
    return _from_entries(store.read())


def _from_entries(data: dict[str, Any]) -> dict[str, Session]:
    return {alias: _from_dict(entry, alias) for alias, entry in _entries(data).items()}


def _with_secrets(session: Session) -> Session:
    secrets = credentials.get(session.credential_key)
    if secrets is None:
        raise NotLoggedIn
    session.cookies = secrets["cookies"]
    session.bearer_token = secrets["bearer_token"]
    return session


def all_sessions() -> dict[str, Session]:
    return {alias: _with_secrets(session) for alias, session in _read_all().items()}


def aliases() -> list[str]:
    return sorted(_read_all())


def listed() -> dict[str, Session]:
    return _read_all()


def current_alias() -> str | None:
    data = store.read()
    sessions = _entries(data)
    if not sessions:
        return None

    alias = data.get(store.CURRENT_KEY)
    if alias not in sessions:
        raise OvError(f"The current instance {alias!r} in {config_file()} is not signed in. Run 'ov use <alias>'.")
    return alias


def is_same_target(session: Session, base_url: str, tenant_id: str) -> bool:
    return session.base_url == base_url.rstrip("/") and session.tenant_id == tenant_id


def unique_alias(base_url: str, preferred: str = "", tenant: str = "", tenant_id: str = "") -> str:
    base_url = base_url.rstrip("/")
    sessions = _read_all()
    if not preferred:
        for alias, session in sessions.items():
            if is_same_target(session, base_url, tenant_id):
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

    known = ", ".join(sorted(sessions))
    raise NotFound(f"No instance matches {ref!r}. Signed in to: {known}.")


def _prefer_default_tenant(matches: list[str], sessions: dict[str, Session]) -> str | None:
    if len(matches) == 1:
        return matches[0]
    if not matches or len({sessions[a].base_url for a in matches}) != 1:
        return None
    plain = [a for a in matches if not sessions[a].tenant]
    return plain[0] if len(plain) == 1 else None


def save(session: Session, make_current: bool = True) -> Session:
    session.saved_at = time.time()

    with store.lock():
        taken = _read_all().get(session.alias)
        if taken is not None and not is_same_target(taken, session.base_url, session.tenant_id):
            session.alias = unique_alias(session.base_url, tenant=session.tenant, tenant_id=session.tenant_id)

        credentials.put(session.credential_key, session.secrets())

        def change(data: dict[str, Any]) -> None:
            data[store.SESSIONS_KEY] = {**_entries(data), session.alias: session.to_dict()}
            if make_current or store.CURRENT_KEY not in data:
                data[store.CURRENT_KEY] = session.alias

        store.mutate(change)

    return session


def find(ref: str | None = None) -> Session:
    sessions = _read_all()
    if not sessions:
        raise NotLoggedIn
    if ref:
        return sessions[resolve(ref)]
    return sessions[current_alias()]


def load(ref: str | None = None) -> Session:
    session = _with_secrets(find(ref))
    if not session.bearer_token and not session.cookies:
        raise NotLoggedIn
    return session


def use(ref: str) -> Session:
    with store.lock():
        alias = resolve(ref)
        store.update(**{store.CURRENT_KEY: alias})
    return _read_all()[alias]


def remove(ref: str) -> Session:
    with store.lock():
        alias = resolve(ref)
        removed = _read_all()[alias]

        def change(data: dict[str, Any]) -> None:
            entries = _entries(data)
            del entries[alias]
            if not entries:
                data.pop(store.SESSIONS_KEY)
                data.pop(store.CURRENT_KEY)
                return

            data[store.SESSIONS_KEY] = entries
            if data[store.CURRENT_KEY] not in entries:
                data[store.CURRENT_KEY] = next(iter(entries))

        remaining = _from_entries(store.mutate(change))
        if not any(s.credential_key == removed.credential_key for s in remaining.values()):
            credentials.delete(removed.credential_key)

    return removed


def clear() -> int:
    with store.lock():
        sessions = _read_all()
        store.update(**{store.SESSIONS_KEY: None, store.CURRENT_KEY: None})
        for key in {s.credential_key for s in sessions.values()}:
            credentials.delete(key)
    return len(sessions)


def expiry_to_epoch(text: str) -> float:
    try:
        deadline = datetime.fromisoformat(text.strip()).timestamp()
    except ValueError as exc:
        raise OvError(f"Unreadable token expiry: {text!r}") from exc

    ttl = deadline - time.time()
    if MIN_PLAUSIBLE_TTL <= ttl <= MAX_PLAUSIBLE_TTL:
        return deadline
    return time.time() + ASSUMED_TTL_SECONDS


def cookies_from_playwright(raw: list[dict[str, Any]], host: str) -> dict[str, str]:
    host = host.lower()

    def ours(cookie: dict[str, Any]) -> bool:
        domain = cookie["domain"].lstrip(".").lower()
        return host == domain or host.endswith("." + domain)

    return {c["name"]: c["value"] for c in raw if c["value"] and ours(c)}
