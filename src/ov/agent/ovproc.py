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

LOGIN_TIMEOUT_SECONDS = 300


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


# A child process rather than in-process calls: ov keeps per-process state (console, schema
# cache, read-only flag) that parallel tool calls would otherwise share.
def run_ov(
    args: list[str],
    timeout: float = 120,
    read_only: bool = True,
    cancel: Cancel | None = None,
    cwd: Path | None = None,
) -> OvResult:
    env = {
        **os.environ,
        "OV_READONLY": "1" if read_only else "",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "NO_COLOR": "1",
        "COLUMNS": "200",
    }
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Files instead of pipes, so a large response cannot fill a pipe and stall the child.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(
            # -P keeps a stray ov.py in the working directory from shadowing the package.
            [sys.executable, "-P", "-m", "ov", *args],
            cwd=cwd or agent_dir(),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            env=env,
            creationflags=flags,
        )
        timed_out = _wait(process, timeout, cancel)
        out.seek(0)
        err.seek(0)
        return OvResult(
            code=process.returncode if process.returncode is not None else 1,
            stdout=out.read().decode("utf-8", "replace"),
            stderr=_ANSI.sub("", err.read().decode("utf-8", "replace")),
            timed_out=timed_out,
        )


def _wait(process: subprocess.Popen[Any], timeout: float, cancel: Cancel | None) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            process.wait(timeout=0.2)
            return False
        except subprocess.TimeoutExpired:
            pass
        expired = time.monotonic() > deadline
        if expired or (cancel is not None and cancel.is_set()):
            process.kill()
            process.wait()
            return expired


def host_of(value: str) -> str:
    text = value.strip()
    parsed = urlsplit(text if "://" in text else f"https://{text}")
    return (parsed.netloc or text).lower()


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
            }
        )
    return rows


def find_instance(ref: str) -> dict[str, Any] | None:
    wanted = ref.strip().lower()
    host = host_of(ref)
    rows = instances()
    by_alias = [r for r in rows if r["alias"].lower() == wanted]
    by_host = [r for r in rows if r["host"] == host and not r["tenant"]] or [
        r for r in rows if r["host"] == host
    ]
    found = by_alias or by_host
    return found[0] if found else None


_logins: dict[str, tuple[threading.Event, list[OvResult]]] = {}
_logins_lock = threading.Lock()


# Opens a browser for the user; concurrent requests for the same host share one sign-in.
def login(url: str) -> OvResult:
    host = host_of(url)
    with _logins_lock:
        running = _logins.get(host)
        if running is None:
            running = (threading.Event(), [])
            _logins[host] = running
            owner = True
        else:
            owner = False
    done, holder = running
    if not owner:
        done.wait()
        return holder[0]

    try:
        holder.append(
            run_ov(
                ["login", f"https://{host}", "--keep-current", "--timeout", "280"],
                timeout=LOGIN_TIMEOUT_SECONDS,
                read_only=False,
            )
        )
    finally:
        if not holder:
            holder.append(OvResult(1, "", "Sign-in failed."))
        with _logins_lock:
            _logins.pop(host, None)
        done.set()
    return holder[0]
