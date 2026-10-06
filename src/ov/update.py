from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from .errors import OvError
from .paths import home

PACKAGE = "ov-cli"
REPO_URL = "https://github.com/Just-Bax/ov-cli.git"
BRANCH = "master"
GIT_TIMEOUT_SECONDS = 120
INSTALL_TIMEOUT_SECONDS = 600
LOG_LINES = 20
DEPENDENCY_FILES = ("pyproject.toml", "uv.lock")
SYNCHRONIZE = 0x00100000
WAIT_MS = 120_000


@dataclass
class Install:
    checkout: Path | None
    commit: str
    uv_tool: bool


@dataclass
class Plan:
    install: Install
    current: str
    latest: str
    commits: list[str]
    reinstall: bool


def _git(args: list[str], cwd: Path | None = None) -> str:
    if shutil.which("git") is None:
        raise OvError("git is not installed or not on PATH. ov update uses it to fetch the latest code.")

    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise OvError(f"git {' '.join(args[:2])} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def _direct_url() -> dict:
    try:
        text = metadata.distribution(PACKAGE).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        raise OvError(f"{PACKAGE} is not installed as a package, so it cannot update itself.") from None
    if text is None:
        raise OvError(f"{PACKAGE} was installed from a package index; reinstall it with the install script.")
    return json.loads(text)


def _uv_tool() -> bool:
    if shutil.which("uv") is None:
        return False
    tools = subprocess.run(["uv", "tool", "dir"], capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS)
    return tools.returncode == 0 and Path(sys.prefix).resolve().parent == Path(tools.stdout.strip()).resolve()


def detect() -> Install:
    info = _direct_url()
    if info.get("dir_info", {}).get("editable"):
        checkout = Path(url2pathname(unquote(urlsplit(info["url"]).path)))
        if not (checkout / ".git").exists():
            raise OvError(f"ov runs from {checkout}, which is not a git checkout. Update it by hand.")
        return Install(checkout, _git(["rev-parse", "HEAD"], checkout), _uv_tool())

    commit = info.get("vcs_info", {}).get("commit_id", "")
    return Install(None, commit, _uv_tool())


def _checkout_plan(install: Install) -> Plan:
    repo = install.checkout
    assert repo is not None
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    _git(["fetch", "--quiet", "origin", branch], repo)
    latest = _git(["rev-parse", f"origin/{branch}"], repo)
    log = _git(["log", "--oneline", f"{install.commit}..{latest}"], repo)
    changed = _git(["diff", "--name-only", install.commit, latest], repo).splitlines()
    return Plan(
        install,
        install.commit,
        latest,
        log.splitlines(),
        install.uv_tool and any(name in DEPENDENCY_FILES for name in changed),
    )


def _remote_plan(install: Install) -> Plan:
    latest = _git(["ls-remote", REPO_URL, f"refs/heads/{BRANCH}"]).split()[0]
    return Plan(install, install.commit, latest, [], install.commit != latest)


def plan() -> Plan:
    install = detect()
    return _checkout_plan(install) if install.checkout else _remote_plan(install)


def pull(found: Plan) -> None:
    repo = found.install.checkout
    assert repo is not None
    _git(["merge", "--ff-only", found.latest], repo)


def install_command(found: Plan) -> list[str]:
    if found.install.checkout is not None:
        source = str(found.install.checkout)
        return ["uv", "tool", "install", "--force", "--editable", source]
    if found.install.uv_tool:
        source = f"{PACKAGE} @ git+{REPO_URL}@{BRANCH}"
        return ["uv", "tool", "install", "--force", "--reinstall-package", PACKAGE, source]
    return [sys.executable, "-m", "pip", "install", "--upgrade", f"git+{REPO_URL}@{BRANCH}"]


def log_file() -> Path:
    return home() / "update.log"


def reinstall(command: list[str]) -> bool:
    if sys.platform != "win32":
        result = subprocess.run(command, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_SECONDS)
        log_file().write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode != 0:
            tail = "\n".join((result.stderr or result.stdout).splitlines()[-LOG_LINES:])
            raise OvError(f"Reinstall failed:\n{tail}")
        return False

    script = (
        "import ctypes, subprocess\n"
        "kernel = ctypes.windll.kernel32\n"
        f"handle = kernel.OpenProcess({SYNCHRONIZE}, False, {os.getpid()})\n"
        "if handle:\n"
        f"    kernel.WaitForSingleObject(handle, {WAIT_MS})\n"
        "    kernel.CloseHandle(handle)\n"
        f"with open({str(log_file())!r}, 'w', encoding='utf-8') as out:\n"
        f"    subprocess.run({command!r}, stdout=out, stderr=subprocess.STDOUT)\n"
    )
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    python = getattr(sys, "_base_executable", sys.executable)
    subprocess.Popen([python, "-c", script], creationflags=flags, close_fds=True)
    return True
