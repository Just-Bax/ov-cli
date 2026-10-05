from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .. import __version__
from .. import session as session_store
from ..errors import EXIT_AUTH
from ..paths import agent_dir
from .cancel import Cancel

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

DEFAULT_TIMEOUT_SECONDS = 120
LOGIN_TIMEOUT_SECONDS = 300
BROWSER_LOGIN_TIMEOUT_SECONDS = 280
POLL_SECONDS = 0.2
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
) -> OvResult:
    env = {
        **os.environ,
        "OV_READONLY": "1" if read_only else "",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "NO_COLOR": "1",
        "COLUMNS": CONSOLE_COLUMNS,
    }
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(
            [sys.executable, "-P", "-m", "ov", *args],
            cwd=cwd or agent_dir(),
            stdin=subprocess.DEVNULL if stdin is None else subprocess.PIPE,
            stdout=out,
            stderr=err,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if stdin is not None:
            process.stdin.write(stdin.encode())
            process.stdin.close()

        timed_out = _wait(process, timeout, cancel)
        out.seek(0)
        err.seek(0)
        return OvResult(
            code=process.returncode,
            stdout=out.read().decode("utf-8", "replace"),
            stderr=_ANSI.sub("", err.read().decode("utf-8", "replace")),
            timed_out=timed_out,
        )


def _wait(process: subprocess.Popen[Any], timeout: float, cancel: Cancel | None) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            process.wait(timeout=POLL_SECONDS)
        except subprocess.TimeoutExpired:
            expired = time.monotonic() > deadline
            if expired or (cancel is not None and cancel.is_set()):
                process.kill()
                process.wait()
                return expired
        else:
            return False


def host_of(value: str) -> str:
    text = value.strip()
    return urlsplit(text if "://" in text else f"https://{text}").netloc.lower()


def instances() -> list[dict[str, Any]]:
    current = session_store.current_alias()
    rows = []
    for alias, session in sorted(session_store.listed().items()):
        left = session.seconds_left()
        rows.append(
            {
                "alias": alias,
                "url": session.base_url,
                "host": host_of(session.base_url),
                "tenant": session.tenant or None,
                "current": alias == current,
                "expires": session.expires_text or None,
                "valid": session.is_static or (left is not None and left > 0),
                "mode": session.mode,
            }
        )
    return rows


def url_for(host: str) -> str:
    known = next((i["url"] for i in instances() if i["host"] == host_of(host)), None)
    return known or f"https://{host}"


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


def login(url: str, tenant: str = "", token: str = "") -> OvResult:
    url = url.strip().rstrip("/")
    tenant = tenant.strip()
    key = (url.lower(), tenant.lower())
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

    try:
        holder.append(
            run_ov(
                [
                    "login",
                    url,
                    "--keep-current",
                    "--timeout",
                    str(BROWSER_LOGIN_TIMEOUT_SECONDS),
                    *(["--tenant", tenant] if tenant else []),
                    *(["--token", "-"] if token else []),
                ],
                timeout=LOGIN_TIMEOUT_SECONDS,
                read_only=False,
                stdin=token or None,
            )
        )
    finally:
        if not holder:
            holder.append(OvResult(1, "", "Sign-in failed."))
        with _logins_lock:
            _logins.pop(key, None)
        done.set()
    return holder[0]
