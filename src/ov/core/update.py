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
from ov.core.paths import cache_dir

PACKAGE = "ov-cli"
REPO_URL = "https://github.com/Just-Bax/ov-cli.git"
BRANCH = "master"
COMMAND_TIMEOUT_SECONDS = 120
DEPENDENCY_FILES = ("pyproject.toml", "uv.lock")
MIGRATE_ARGS = ("agent", "--migrate")
REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
SOURCE_DIR = "source"
REPO_DIR = "repo"


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


def _requirement_name(requirement: str) -> str:
    name = REQUIREMENT_NAME.match(requirement)
    if name is None:
        raise OvError(f"Cannot read the requirement {requirement!r} of {PACKAGE}.")
    return name.group()


def _runtime(requirements: list[str]) -> list[str]:
    return [requirement for requirement in requirements if "extra ==" not in requirement]


def _missing(requirements: list[str]) -> list[str]:
    missing = []
    for requirement in _runtime(requirements):
        name = _requirement_name(requirement)
        try:
            metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)

    return missing


def missing_dependencies() -> list[str]:
    return _missing(_declared_requirements())


def require_dependencies() -> None:
    missing = missing_dependencies()
    if missing:
        raise OvError(f"ov is missing packages it needs ({', '.join(missing)}). Run 'ov update' to install them.")


def _uv_tool() -> bool:
    if shutil.which("uv") is None:
        return False
    tools = subprocess.run(["uv", "tool", "dir"], capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS)
    return tools.returncode == 0 and Path(sys.prefix).resolve().parent == Path(tools.stdout.strip()).resolve()


def source_root() -> Path:
    return cache_dir() / SOURCE_DIR


def _source_commit(info: dict) -> str:
    if "dir_info" not in info:
        return ""
    source = _checkout_of(info)
    return source.name if source.parent.resolve() == source_root().resolve() else ""


def detect() -> Install:
    info = _direct_url()
    if _editable(info):
        checkout = _checkout_of(info)
        if not (checkout / ".git").exists():
            raise OvError(f"ov runs from {checkout}, which is not a git checkout. Update it by hand.")
        return Install(checkout, _git(["rev-parse", "HEAD"], checkout), _uv_tool())

    commit = info.get("vcs_info", {}).get("commit_id") or _source_commit(info)
    if not commit and "archive_info" not in info:
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


def _installer(install: Install) -> list[str]:
    if install.uv_tool:
        return ["uv", "pip", "install", "--python", sys.executable]
    return [sys.executable, "-m", "pip", "install"]


def _force(install: Install) -> list[str]:
    return ["--reinstall-package", PACKAGE] if install.uv_tool else ["--force-reinstall"]


def editable_command(install: Install) -> list[str]:
    return [*_installer(install), "--editable", str(install.checkout)]


def _requirement_key(requirement: str) -> tuple[str, tuple[str, ...]]:
    text = requirement.split(";")[0].replace(" ", "")
    name = _requirement_name(text)
    specifiers = sorted(part for part in text[len(name) :].split(",") if part)
    return name.lower().replace("_", "-"), tuple(specifiers)


def _requirements_of(source: Path) -> list[str]:
    with (source / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]["dependencies"]


def dependencies_changed(requirements: list[str]) -> bool:
    installed = _runtime(metadata.requires(PACKAGE) or [])
    wanted = {_requirement_key(requirement) for requirement in _runtime(requirements)}
    return wanted != {_requirement_key(requirement) for requirement in installed} or bool(_missing(requirements))


def source_commands(install: Install, source: Path) -> list[list[str]]:
    package = [*_installer(install), "--no-deps", *_force(install), str(source)]
    requirements = _requirements_of(source)
    if not dependencies_changed(requirements):
        return [package]
    return [[*_installer(install), *_runtime(requirements)], package]


def fetch_source() -> Path:
    root = source_root()
    repo = root / REPO_DIR
    if not (repo / ".git").exists():
        _git(["init", "--quiet", str(repo)])
        _git(["remote", "add", "origin", REPO_URL], repo)

    _git(["fetch", "--quiet", "--depth", "1", "origin", BRANCH], repo)
    commit = _git(["rev-parse", "FETCH_HEAD"], repo)

    target = root / commit
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    _git([f"--work-tree={target}", "checkout", "--force", commit, "--", "."], repo)
    return target


def _prune_sources(keep: Path) -> None:
    for entry in keep.parent.iterdir():
        if entry.is_dir() and entry.name not in (REPO_DIR, keep.name):
            shutil.rmtree(entry)


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


def _install(command: list[str]) -> None:
    result = subprocess.run(command, stdout=sys.stderr)
    if result.returncode != 0:
        raise OvError(
            f"Installing the update failed: {' '.join(command[:3])} exited with {result.returncode} (see above). "
            "Run 'ov update' again to retry."
        )


def reinstall(found: Plan) -> None:
    if found.install.checkout is not None:
        _install(editable_command(found.install))
        return

    source = fetch_source()
    for command in source_commands(found.install, source):
        _install(command)
    _prune_sources(source)
