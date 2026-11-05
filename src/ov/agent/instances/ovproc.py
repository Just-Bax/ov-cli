from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ov import __version__
from ov.agent.api.screen import Screen, close_screen, open_screen, screen_key
from ov.agent.engine.cancel import Cancel
from ov.agent.instances import access
from ov.cli.context import TIMEOUT_ENV
from ov.core.errors import EXIT_AUTH
from ov.core.paths import agent_dir
from ov.core.procs import kill_tree, spawn_options, wait_or_stop
from ov.onevizion import session as session_store

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

DEFAULT_TIMEOUT_SECONDS = 120
LOGIN_TIMEOUT_SECONDS = 300
BROWSER_LOGIN_TIMEOUT_SECONDS = 280
REMEMBER_DAYS = 30
REMEMBER_TIMEOUT_SECONDS = 60
MS_PER_SECOND = 1000
STOP_GRACE_SECONDS = 10
TIMEOUT_GRACE_SECONDS = 15
SIGN_IN_CANCELLED = "Sign-in cancelled."
CONSOLE_COLUMNS = "200"


@dataclass
class OvResult:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def is_auth(self) -> bool:
        return self.code == EXIT_AUTH

    @property
    def message(self) -> str:
        return (self.stderr or self.stdout).strip()


def version() -> str:
    return f"ov {__version__}"


def run_ov(
    args: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    read_only: bool = True,
    cancel: Cancel | None = None,
    cwd: Path | None = None,
    stdin: str | None = None,
    extra_env: dict[str, str] | None = None,
    hold_stdin: bool = False,
) -> OvResult:
    env = {
        **os.environ,
        **(extra_env or {}),
        "OV_READONLY": "1" if read_only else "",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "NO_COLOR": "1",
        "COLUMNS": CONSOLE_COLUMNS,
        TIMEOUT_ENV: str(timeout),
    }
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(
            [sys.executable, "-P", "-m", "ov", *args],
            cwd=cwd or agent_dir(),
            stdin=subprocess.DEVNULL if stdin is None and not hold_stdin else subprocess.PIPE,
            stdout=out,
            stderr=err,
            env=env,
            **spawn_options(),
        )
        if stdin is not None:
            process.stdin.write(stdin.encode())
            process.stdin.close()

        timed_out = _wait(process, timeout + TIMEOUT_GRACE_SECONDS, cancel, hold_stdin)
        out.seek(0)
        err.seek(0)
        return OvResult(
            code=process.returncode,
            stdout=out.read().decode("utf-8", "replace"),
            stderr=_ANSI.sub("", err.read().decode("utf-8", "replace")),
            timed_out=timed_out,
        )


def _wait(process: subprocess.Popen[Any], timeout: float, cancel: Cancel | None, held: bool) -> bool:
    expired = wait_or_stop(process, timeout, lambda: cancel is not None and cancel.is_set(), lambda p: _stop(p, held))
    if held:
        process.stdin.close()
    return expired


def _stop(process: subprocess.Popen[Any], held: bool) -> None:
    if held:
        process.stdin.close()
        try:
            process.wait(timeout=STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            kill_tree(process)
        return
    kill_tree(process)


def host_of(value: str) -> str:
    text = value.strip()
    return urlsplit(text if "://" in text else f"https://{text}").netloc.lower()


def instances() -> list[dict[str, Any]]:
    current = session_store.current_alias()
    rows = []
    for alias, session in sorted(session_store.listed().items()):
        rows.append(
            {
                "alias": alias,
                "url": session.base_url,
                "host": host_of(session.base_url),
                "tenant": session.tenant or None,
                "current": alias == current,
                "mode": session.mode,
                "valid": _works(session),
                "endedAt": _ms(session.ended_at),
                "lastWorkedAt": _ms(session.saved_at),
                "expiresAt": _ms(session.expires_at) if session.is_static else None,
            }
        )
    return rows


def _works(session: session_store.Session) -> bool:
    if session.ended_at:
        return False
    left = session.seconds_left()
    return left is None or left > 0 if session.is_static else True


def _ms(seconds: float) -> int | None:
    return int(seconds * MS_PER_SECOND) if seconds else None


def remember(alias: str) -> OvResult:
    return run_ov(["remember", alias, "--days", str(REMEMBER_DAYS)], timeout=REMEMBER_TIMEOUT_SECONDS, read_only=False)


def signed_in_row(host: str, tenant: str) -> dict[str, Any] | None:
    wanted = host_of(host)
    return next((r for r in instances() if r["host"] == wanted and (r["tenant"] or "") == tenant), None)


def url_for(host: str) -> str:
    known = next((i["url"] for i in instances() if i["host"] == host_of(host)), None)
    return known or f"https://{host}"


def web_cookies(alias: str) -> dict[str, str]:
    return dict(session_store.load(alias).cookies)


def find_instance(ref: str) -> dict[str, Any] | None:
    wanted = ref.strip().lower()
    host = host_of(ref)
    rows = instances()
    by_alias = [r for r in rows if r["alias"].lower() == wanted]
    by_host = [r for r in rows if r["host"] == host and not r["tenant"]] or [r for r in rows if r["host"] == host]
    found = by_alias or by_host
    return found[0] if found else None


_logins: dict[tuple[str, str], tuple[threading.Event, list[OvResult]]] = {}
_logins_lock = threading.Lock()


def login(
    url: str, tenant: str = "", token: str = "", screen: tuple[int, int] | None = None, remember: bool = False
) -> OvResult:
    url = url.strip().rstrip("/")
    tenant = tenant.strip()
    key = screen_key(url, tenant)
    with _logins_lock:
        running = _logins.get(key)
        owner = running is None
        if running is None:
            running = (threading.Event(), [])
            _logins[key] = running

    done, holder = running
    if not owner:
        done.wait()
        return holder[0]

    shown = open_screen(key, *screen) if screen and not token else None
    try:
        holder.append(_run_login(url, tenant, token, shown, remember and not token))
        _check_access(url, tenant, holder[0])
    finally:
        if shown:
            close_screen(key, shown)
        if not holder:
            holder.append(OvResult(1, "", "Sign-in failed."))
        with _logins_lock:
            _logins.pop(key, None)
        done.set()
    return holder[0]


def _check_access(url: str, tenant: str, result: OvResult) -> None:
    if result.code != 0:
        return

    found = signed_in_row(url, tenant)
    if found is not None:
        access.check_later(found["alias"])


def _run_login(url: str, tenant: str, token: str, shown: Screen | None, remember: bool) -> OvResult:
    result = run_ov(
        [
            "login",
            url,
            "--keep-current",
            "--timeout",
            str(BROWSER_LOGIN_TIMEOUT_SECONDS),
            *(["--tenant", tenant] if tenant else []),
            *(["--token", "-"] if token else []),
            *(["--remember", str(REMEMBER_DAYS)] if remember else []),
        ],
        timeout=LOGIN_TIMEOUT_SECONDS,
        read_only=False,
        stdin=token or None,
        extra_env=shown.env if shown else None,
        hold_stdin=shown is not None,
        cancel=shown.cancel if shown else None,
    )
    if shown and shown.cancel.is_set():
        return OvResult(1, "", SIGN_IN_CANCELLED)
    return result
