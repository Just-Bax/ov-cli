from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

TASKKILL_TIMEOUT_SECONDS = 30
POLL_SECONDS = 0.2


def spawn_options() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def wait_or_stop(
    process: subprocess.Popen[Any],
    timeout: float,
    cancelled: Callable[[], bool],
    stop: Callable[[subprocess.Popen[Any]], None],
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            process.wait(timeout=POLL_SECONDS)
        except subprocess.TimeoutExpired:
            expired = time.monotonic() > deadline
            if expired or cancelled():
                stop(process)
                return expired
        else:
            return False


def kill_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            capture_output=True,
            timeout=TASKKILL_TIMEOUT_SECONDS,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)

    process.wait()
