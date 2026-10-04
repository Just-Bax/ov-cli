from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..paths import agent_dir
from . import db
from .workspace import within

REPO_PREFIX = "repo:"
MAX_MATCHES = 80
MAX_LINE = 300

_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_GIT_URL = re.compile(r"^(https?://|ssh://|git@)", re.IGNORECASE)
_GITHUB = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


class SourceError(Exception):
    pass


def git(args: list[str], cwd: Path, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise SourceError("git is not installed or not on PATH.") from None
    except subprocess.TimeoutExpired:
        raise SourceError(f"git {args[0]} timed out after {timeout:.0f}s.") from None


def is_git_url(location: str) -> bool:
    return bool(_GIT_URL.match(location.strip()))


def _clone_dir(name: str) -> Path:
    return agent_dir("sources") / name


def _describe(row: dict[str, Any]) -> dict[str, Any]:
    git_source = is_git_url(row["location"])
    path = _clone_dir(row["name"]) if git_source else Path(row["location"]).expanduser()
    return {
        "name": row["name"],
        "description": row["description"],
        "location": row["location"],
        "kind": "git" if git_source else "folder",
        "path": str(path),
        "ready": path.is_dir(),
    }


def list_sources() -> list[dict[str, Any]]:
    return [_describe(row) for row in db.source_rows()]


def _find(name: str) -> dict[str, Any]:
    found = next((s for s in list_sources() if s["name"] == name), None)
    if found is None:
        raise SourceError(f"Unknown source: {name}")
    return found


def add(name: str, description: str, location: str) -> dict[str, Any]:
    name, location = name.strip().lower(), location.strip()
    if not _NAME.match(name):
        raise SourceError("Name: lowercase letters, digits, dots, dashes and underscores.")
    if any(s["name"] == name for s in list_sources()):
        raise SourceError(f"A source named {name} already exists.")
    _prepare(name, location)
    db.put_source(name, description.strip(), location)
    return _find(name)


def update(name: str, description: str, location: str) -> dict[str, Any]:
    current = _find(name)
    location = location.strip() or current["location"]
    if location != current["location"]:
        _remove_clone(current)
        _prepare(name, location)
    db.put_source(name, description.strip(), location)
    return _find(name)


def _prepare(name: str, location: str) -> None:
    if not location:
        raise SourceError("Give a folder path or a git URL.")
    if not is_git_url(location):
        if not Path(location).expanduser().is_dir():
            raise SourceError(f"No such folder: {location}")
        return

    target = _clone_dir(name)
    if target.exists():
        _rmtree(target)
    result = git(["clone", "--depth", "1", location, str(target)], agent_dir("sources"), 600)
    if result.returncode != 0:
        raise SourceError(f"Could not clone {location}: {result.stderr.strip()[-400:]}")


def sync(name: str) -> dict[str, Any]:
    source = _find(name)
    if source["kind"] != "git":
        return source
    if not source["ready"]:
        _prepare(name, source["location"])
        return _find(name)
    result = git(["pull", "--ff-only"], Path(source["path"]), 300)
    if result.returncode != 0:
        raise SourceError(f"git pull failed: {result.stderr.strip()[-400:]}")
    return _find(name)


def remove(name: str) -> None:
    source = _find(name)
    _remove_clone(source)
    db.delete_source(name)


def _remove_clone(source: dict[str, Any]) -> None:
    if source["kind"] == "git" and Path(source["path"]).exists():
        _rmtree(Path(source["path"]))


# git marks pack files read-only, which rmtree cannot delete on Windows.
def _rmtree(path: Path) -> None:
    def unlock(function: Any, target: str, _: Any) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=unlock)
    else:
        shutil.rmtree(path, onerror=unlock)


def root(ref: str) -> Path:
    if ref.startswith(REPO_PREFIX):
        name = ref[len(REPO_PREFIX) :]
        path = agent_dir("repos") / name
        if not _NAME.match(name.lower()) or not path.is_dir():
            raise SourceError(f"Repo {name} is not cloned. Call github_clone first.")
        return path

    source = _find(ref)
    if not source["ready"]:
        raise SourceError(f"Source {ref} is not available at {source['path']}.")
    return Path(source["path"])


def search(ref: str, pattern: str, pathspec: str = "", ignore_case: bool = False) -> str:
    base = root(ref)
    args = ["grep", "-n", "-I", "-E", "--max-count", "20"]
    if not (base / ".git").exists():
        args.insert(1, "--no-index")
    if ignore_case:
        args.append("-i")
    args += ["-e", pattern]
    if pathspec:
        args += ["--", pathspec]

    result = git(args, base, 60)
    if result.returncode == 1:
        return "No matches."
    if result.returncode != 0:
        raise SourceError(result.stderr.strip() or "git grep failed")
    lines = [line for line in result.stdout.split("\n") if line]
    shown = [line if len(line) <= MAX_LINE else line[:MAX_LINE] + "..." for line in lines]
    if len(lines) > MAX_MATCHES:
        extra = len(lines) - MAX_MATCHES
        shown = shown[:MAX_MATCHES] + [f"... {extra} more matches; narrow the pattern or path."]
    return "\n".join(shown)


def read(ref: str, rel: str, start: int = 1, end: int | None = None) -> str:
    base = root(ref)
    path = within(base, rel)
    if not path.exists():
        raise SourceError(f"No such file in {ref}: {rel}")
    if path.is_dir():
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        return "\n".join(p.name + ("/" if p.is_dir() else "") for p in entries if p.name != ".git")

    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    first = max(1, start)
    last = min(len(lines), end or first + 399)
    body = "\n".join(f"{first + i}: {line}" for i, line in enumerate(lines[first - 1 : last]))
    return f"{body}\n... ({len(lines)} lines total)" if last < len(lines) else body


def clone_repo(ref: str) -> dict[str, Any]:
    ref = ref.strip()
    match = _GITHUB.search(ref)
    if match:
        url = f"https://github.com/{match.group(1)}/{match.group(2)}.git"
        name = f"{match.group(1)}-{match.group(2)}"
    elif is_git_url(ref):
        url, name = ref, ref.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    else:
        raise SourceError(f"Not a git URL: {ref}")
    name = name.lower()
    if not _NAME.match(name):
        raise SourceError(f"Bad repo name: {name}")

    target = agent_dir("repos") / name
    if (target / ".git").exists():
        origin = git(["remote", "get-url", "origin"], target).stdout.strip()
        if origin.removesuffix(".git").lower() != url.removesuffix(".git").lower():
            raise SourceError(f"repo:{name} is already a clone of {origin}.")
        result = git(["pull", "--ff-only"], target, 120)
        if result.returncode != 0:
            raise SourceError(f"git pull failed: {result.stderr.strip()[-400:]}")
    else:
        result = git(["clone", "--depth", "1", url, str(target)], agent_dir("repos"), 600)
        if result.returncode != 0:
            raise SourceError(
                f"Could not clone {url}: {result.stderr.strip()[-400:]}. "
                "Check the URL; the user may need access to that repo."
            )
    files = git(["ls-files"], target).stdout.split("\n")
    return {"repo": f"{REPO_PREFIX}{name}", "files": [f for f in files if f][:300]}
