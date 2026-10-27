from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from ov.core.errors import EXIT_IN_USE, OvError

PACKAGE = "ov-cli"
REPO_URL = "https://github.com/Just-Bax/ov-cli.git"
BRANCH = "master"
COMMAND_TIMEOUT_SECONDS = 120
DEPENDENCY_FILES = ("pyproject.toml", "uv.lock")
MIGRATE_ARGS = ("agent", "--migrate")
REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


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
        timeout=COMMAND_TIMEOUT_SECONDS,
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


def _editable(info: dict) -> bool:
    return bool(info.get("dir_info", {}).get("editable"))


def _checkout_of(info: dict) -> Path:
    return Path(url2pathname(unquote(urlsplit(info["url"]).path)))


def _declared_requirements() -> list[str]:
    info = _direct_url()
    if not _editable(info):
        return metadata.requires(PACKAGE) or []
    with (_checkout_of(info) / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]["dependencies"]


def missing_dependencies() -> list[str]:
    missing = []
    for requirement in _declared_requirements():
        if "extra ==" in requirement:
            continue

        name = REQUIREMENT_NAME.match(requirement)
        if name is None:
            raise OvError(f"Cannot read the requirement {requirement!r} of {PACKAGE}.")

        try:
            metadata.distribution(name.group())
        except metadata.PackageNotFoundError:
            missing.append(name.group())
    return missing


def require_dependencies() -> None:
    missing = missing_dependencies()
    if missing:
        raise OvError(f"ov is missing packages it needs ({', '.join(missing)}). Run 'ov update' to install them.")


def _uv_tool() -> bool:
    if shutil.which("uv") is None:
        return False
    tools = subprocess.run(["uv", "tool", "dir"], capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
    return tools.returncode == 0 and Path(sys.prefix).resolve().parent == Path(tools.stdout.strip()).resolve()


def detect() -> Install:
    info = _direct_url()
    if _editable(info):
        checkout = _checkout_of(info)
        if not (checkout / ".git").exists():
            raise OvError(f"ov runs from {checkout}, which is not a git checkout. Update it by hand.")
        return Install(checkout, _git(["rev-parse", "HEAD"], checkout), _uv_tool())

    commit = info.get("vcs_info", {}).get("commit_id")
    if not commit:
        raise OvError(
            f"{PACKAGE} was not installed from git, so its version is unknown. Reinstall it with the install script."
        )
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
        any(name in DEPENDENCY_FILES for name in changed) or bool(missing_dependencies()),
    )


def _remote_plan(install: Install) -> Plan:
    latest = _git(["ls-remote", REPO_URL, f"refs/heads/{BRANCH}"]).split()[0]
    return Plan(install, install.commit, latest, [], install.commit != latest)


def plan() -> Plan:
    install = detect()
    found = _checkout_plan(install) if install.checkout else _remote_plan(install)
    if found.current == found.latest and missing_dependencies():
        return Plan(install, found.current, found.latest, found.commits, True)
    return found


def pull(found: Plan) -> None:
    repo = found.install.checkout
    assert repo is not None
    _git(["merge", "--ff-only", found.latest], repo)


def install_command(found: Plan) -> list[str]:
    if found.install.uv_tool:
        return ["uv", "tool", "upgrade", "--reinstall-package", PACKAGE, PACKAGE]

    if found.install.checkout is not None:
        return [sys.executable, "-m", "pip", "install", "--editable", str(found.install.checkout)]

    return [sys.executable, "-m", "pip", "install", "--upgrade", f"git+{REPO_URL}@{BRANCH}"]


def migrate_command() -> list[str]:
    return [sys.executable, "-m", "ov", *MIGRATE_ARGS]


def migrate() -> bool:
    result = subprocess.run(
        migrate_command(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode == EXIT_IN_USE:
        return False

    if result.returncode != 0:
        raise OvError((result.stdout + result.stderr).strip() or "Upgrading the agent database failed.")
    return True


def reinstall(command: list[str]) -> None:
    result = subprocess.run(command, stdout=sys.stderr)
    if result.returncode != 0:
        raise OvError(
            f"Installing the update failed: {' '.join(command[:3])} exited with {result.returncode} (see above). "
            "Run 'ov update' again to retry."
        )
