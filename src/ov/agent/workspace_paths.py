from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ov.agent import workspace
from ov.agent.workspace import ProjectError

MAX_INDEXED_PATHS = 50_000
MAX_PATH_RESULTS = 30
INDEX_TTL_SECONDS = 30
LIST_TIMEOUT_SECONDS = 30

_index: dict[str, tuple[float, list[str]]] = {}
_lock = threading.Lock()


def _repo_files(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=off", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=LIST_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ProjectError(f"git ls-files in {workspace.relative(repo) or '.'}: {result.stderr.strip()}")

    prefix = workspace.relative(repo)
    return [f"{prefix}/{path}" if prefix else path for path in result.stdout.split("\0") if path]


def _folders(files: list[str]) -> set[str]:
    found: set[str] = set()
    for path in files:
        parts = path.split("/")[:-1]
        found.update("/".join(parts[: depth + 1]) + "/" for depth in range(len(parts)))
    return found


def _build(base: Path) -> list[str]:
    repos, loose = workspace.repos_and_loose_files(base, [])
    files = [workspace.relative(path) for path in loose]
    for repo in repos:
        files += _repo_files(repo)

    return sorted(_folders(files) | set(files))[:MAX_INDEXED_PATHS]


def _paths() -> list[str]:
    base = workspace.root()
    key = str(base)
    with _lock:
        cached = _index.get(key)
        if cached and time.monotonic() - cached[0] < INDEX_TTL_SECONDS:
            return cached[1]

        paths = _build(base)
        _index[key] = (time.monotonic(), paths)
        return paths


def _subsequence(text: str, query: str) -> bool:
    remaining = iter(text)
    return all(char in remaining for char in query)


def _score(path: str, query: str) -> int | None:
    full = path.rstrip("/").lower()
    name = full.rsplit("/", 1)[-1]
    if "/" not in query:
        if name == query:
            return 0
        if name.startswith(query):
            return 1
        if query in name:
            return 2

    if query in full:
        return 3
    if _subsequence(full, query):
        return 4
    return None


def _row(path: str) -> dict[str, Any]:
    return {"path": path.rstrip("/"), "dir": path.endswith("/")}


def find(query: str) -> list[dict[str, Any]]:
    if not workspace.configured():
        return []

    wanted = query.strip().lower().lstrip("./")
    if not wanted:
        return [{"path": row["path"], "dir": row["dir"]} for row in workspace.entries("")[:MAX_PATH_RESULTS]]

    scored = [(score, path) for path in _paths() if (score := _score(path, wanted)) is not None]
    scored.sort(key=lambda item: (item[0], item[1].count("/"), len(item[1])))
    return [_row(path) for _, path in scored[:MAX_PATH_RESULTS]]
