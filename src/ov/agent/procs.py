from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any

TASKKILL_TIMEOUT_SECONDS = 30


def spawn_options() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


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
