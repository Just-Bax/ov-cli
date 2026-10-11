from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import db
from .cancel import Cancel

SKIPPED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target", ".idea", ".gradle"}
MAX_LIST_ENTRIES = 400
MAX_MATCHES = 200
MAX_FILE_BYTES = 2_000_000
MAX_READ_LINES = 400
MAX_LINE_CHARS = 400
MAX_OUTPUT_CHARS = 30_000
DEFAULT_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 1800
POLL_SECONDS = 0.2
BINARY_SNIFF_BYTES = 4096
SEARCH_WORKERS = 6
SEARCH_TIMEOUT_SECONDS = 120

RISKY_COMMANDS = [
    (re.compile(r"\b(rm|rmdir|rd|del|erase|Remove-Item|ri)\b", re.IGNORECASE), "deletes files"),
    (re.compile(r"\bgit\s+push\b", re.IGNORECASE), "pushes to a remote"),
    (
        re.compile(r"\bgit\s+(reset\s+--hard|clean|rebase|filter-branch|stash\s+(drop|clear))\b", re.IGNORECASE),
        "rewrites git history or drops work",
    ),
    (re.compile(r"\bgit\s+(checkout|restore)\s+(--\s|\.\s*$|-f\b)", re.IGNORECASE), "discards local changes"),
    (
        re.compile(r"\bgit\s+branch\s+-D\b|\bgit\s+commit\b.*--amend\b|\bgit\b.*\s--force\b", re.IGNORECASE),
        "rewrites git history",
    ),
    (
        re.compile(r"\b(format|shutdown|Restart-Computer|Stop-Computer|diskpart|reg\s+delete)\b", re.IGNORECASE),
        "changes the system",
    ),
    (re.compile(r"\b(kill|taskkill|Stop-Process|pkill)\b", re.IGNORECASE), "stops processes"),
    (
        re.compile(r"\b(npm|pnpm|yarn|twine|uv)\s+publish\b|\bdocker\s+(push|rm|rmi|system\s+prune)\b", re.IGNORECASE),
        "publishes or removes artifacts",
    ),
    (
        re.compile(r"\b(Invoke-Expression|iex)\b|\|\s*(sh|bash|pwsh|powershell)\b", re.IGNORECASE),
        "runs downloaded code",
    ),
    (
        re.compile(
            r"\bgh\s+(pr\s+(merge|close|create|comment|review|edit|ready|reopen)"
            r"|issue\s+(create|close|comment|edit|delete|reopen|transfer)"
            r"|release\s+(create|delete|edit|upload)|repo\s+(create|delete|fork|edit|rename|archive)"
            r"|workflow\s+(run|enable|disable)|run\s+(cancel|rerun|delete)"
            r"|(secret|variable|label)\s+(set|create|delete|edit))\b",
            re.IGNORECASE,
        ),
        "changes something on GitHub",
    ),
    (
        re.compile(
            r"\bgh\s+api\b.*(-X\s*|--method[\s=]+)(POST|PUT|PATCH|DELETE)|\bgh\s+api\b.*\s-[fF]\s", re.IGNORECASE
        ),
        "changes something on GitHub",
    ),
    (re.compile(r"\bmklink\b|\bNew-Item\b.*-ItemType\s+(Junction|SymbolicLink)", re.IGNORECASE), "creates links"),
]
_WINDOWS_PATH = r"[A-Za-z]:[\\/][^\s\"'|;&]*|~[\\/][^\s\"'|;&]*"
_POSIX_PATH = r"/[^\s\"'|;&]+|~/[^\s\"'|;&]*"
_ABSOLUTE = re.compile(rf"(?<![\w:./-])({_WINDOWS_PATH if sys.platform == 'win32' else _POSIX_PATH})")


class ProjectError(Exception):
    pass


def configured() -> bool:
    return bool(db.get_settings()["workspace"])


def root() -> Path:
    value = db.get_settings()["workspace"]
    if not value:
        raise ProjectError("No workspace folder is set. Ask the user to pick one in Settings > Workspace.")

    path = Path(value).expanduser()
    if not path.is_dir():
        raise ProjectError(f"The workspace folder {path} does not exist.")
    return path.resolve()


def validate_folder(value: str) -> str:
    if not value.strip():
        return ""

    path = Path(value.strip()).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError(f"Not an existing folder: {value}")
    return str(path.resolve())


def resolve(rel: str) -> Path:
    base = root()
    text = (rel or ".").strip().replace("\\", "/")
    candidate = Path(text)
    target = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if target != base and base not in target.parents:
        raise ProjectError(f"{rel} is outside the workspace {base}.")
    return target


def relative(path: Path) -> str:
    rel = path.relative_to(root()).as_posix()
    return rel if rel != "." else ""


def _skipped(name: str) -> bool:
    return name in SKIPPED_DIRS


def entries(rel: str) -> list[dict[str, Any]]:
    folder = resolve(rel)
    if not folder.is_dir():
        raise ProjectError(f"Not a folder: {rel}")

    rows = []
    for child in folder.iterdir():
        if child.is_dir() and _skipped(child.name):
            continue
        rows.append({"name": child.name, "path": relative(child), "dir": child.is_dir()})
    return sorted(rows, key=lambda r: (not r["dir"], r["name"].lower()))


def listing(rel: str, pattern: str) -> str:
    folder = resolve(rel)
    if not pattern:
        rows = entries(rel)
        lines = [f"{r['name']}/" if r["dir"] else r["name"] for r in rows[:MAX_LIST_ENTRIES]]
        more = f"\n... {len(rows) - MAX_LIST_ENTRIES} more" if len(rows) > MAX_LIST_ENTRIES else ""
        return f"{relative(folder) or '.'}:\n" + "\n".join(lines) + more

    found = []
    for path in _files(folder):
        rel_path = relative(path)
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(path.name, pattern):
            found.append(rel_path)
            if len(found) >= MAX_LIST_ENTRIES:
                break
    return "\n".join(found) or f"No files match {pattern}."


def _files(folder: Path):
    for current, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not _skipped(d))
        for name in sorted(files):
            yield Path(current) / name


def _is_text(path: Path) -> bool:
    if path.stat().st_size > MAX_FILE_BYTES:
        return False
    with path.open("rb") as handle:
        return b"\0" not in handle.read(BINARY_SNIFF_BYTES)


_BRACES = re.compile(r"\{([^{}]*)\}")


def expand_glob(glob: str) -> list[str]:
    match = _BRACES.search(glob)
    if not match:
        return [glob] if glob else []
    head, tail = glob[: match.start()], glob[match.end() :]
    return [g for part in match.group(1).split(",") for g in expand_glob(f"{head}{part}{tail}")]


def search(pattern: str, rel: str, glob: str, ignore_case: bool) -> str:
    target = resolve(rel)
    if not target.exists():
        raise ProjectError(f"No such file or folder: {rel}")
    if target.is_file():
        return "\n".join(_matches(target, _regex(pattern, ignore_case))) or "No matches."

    globs = expand_glob(glob)
    if shutil.which("rg"):
        return _ripgrep(pattern, target, globs, ignore_case)
    return _grep_folder(target, pattern, globs, ignore_case)


def _regex(pattern: str, ignore_case: bool) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise ProjectError(f"Bad regex: {exc}") from None


def _grep_folder(folder: Path, pattern: str, globs: list[str], ignore_case: bool) -> str:
    regex = _regex(pattern, ignore_case)

    repos, loose = _repos_and_loose_files(folder, globs)
    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as pool:
        found = list(pool.map(lambda repo: _git_grep(repo, pattern, globs, ignore_case), repos))

    hits = [hit for batch in found for hit in batch]
    for path in loose:
        hits += _matches(path, regex)
    if len(hits) > MAX_MATCHES:
        return "\n".join(hits[:MAX_MATCHES]) + f"\n[{len(hits)} matches; narrow the search]"
    return "\n".join(hits) or "No matches."


def _repo_of(folder: Path) -> Path | None:
    base = root()
    for candidate in (folder, *folder.parents):
        if (candidate / ".git").exists():
            return candidate
        if candidate == base:
            return None
    return None


def _repos_and_loose_files(folder: Path, globs: list[str]) -> tuple[list[Path], list[Path]]:
    owner = _repo_of(folder)
    if owner is not None:
        return [folder], []

    repos: list[Path] = []
    loose: list[Path] = []
    for current, dirs, files in os.walk(folder):
        here = Path(current)
        if (here / ".git").exists():
            repos.append(here)
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not _skipped(d))
        loose += [here / name for name in sorted(files) if _wanted(here / name, globs)]
    return repos, loose


def _wanted(path: Path, globs: list[str]) -> bool:
    matches_glob = not globs or any(
        fnmatch.fnmatch(path.name, glob) or fnmatch.fnmatch(relative(path), glob) for glob in globs
    )
    return matches_glob and _is_text(path)


def _git_grep(repo: Path, pattern: str, globs: list[str], ignore_case: bool) -> list[str]:
    args = ["git", "-c", "core.quotepath=off", "grep", "-n", "-I", "-P", "--untracked", "--max-count", "50"]
    args += ["-i"] if ignore_case else []
    args += ["-e", pattern, "--", *([f"*{g}" if "/" not in g else g for g in globs] or ["."])]
    result = subprocess.run(
        args,
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    if result.returncode > 1:
        raise ProjectError(f"git grep in {relative(repo) or '.'}: {result.stderr.strip()}")

    prefix = relative(repo)
    lines = []
    for line in result.stdout.splitlines():
        path, _, rest = line.partition(":")
        number, _, text = rest.partition(":")
        full = f"{prefix}/{path}" if prefix else path
        lines.append(f"{full}:{number}: {text.strip()[:MAX_LINE_CHARS]}")
    return lines


def _matches(path: Path, regex: re.Pattern[str]) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [
        f"{relative(path)}:{number}: {line.strip()[:MAX_LINE_CHARS]}"
        for number, line in enumerate(lines, 1)
        if regex.search(line)
    ]


def _ripgrep(pattern: str, folder: Path, globs: list[str], ignore_case: bool) -> str:
    args = ["rg", "-n", "--no-heading", "--max-columns", str(MAX_LINE_CHARS), "-m", "50"]
    args += ["-i"] if ignore_case else []
    args += [arg for glob in globs for arg in ("-g", glob)]
    result = subprocess.run(
        [*args, "-e", pattern, "."], cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode > 1:
        raise ProjectError(result.stderr.strip() or "rg failed")

    prefix = relative(folder)
    lines = [f"{prefix}/{line}" if prefix else line for line in result.stdout.splitlines()]
    if len(lines) > MAX_MATCHES:
        return "\n".join(lines[:MAX_MATCHES]) + f"\n[{len(lines)} matches; narrow the search]"
    return "\n".join(lines) or "No matches."


def read(rel: str, start: int, end: int | None) -> str:
    path = resolve(rel)
    if not path.is_file():
        raise ProjectError(f"No such file: {rel}")
    if not _is_text(path):
        raise ProjectError(f"{rel} is binary or larger than {MAX_FILE_BYTES} bytes.")

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    first = max(start, 1)
    last = min(end or first + MAX_READ_LINES - 1, first + MAX_READ_LINES - 1, len(lines))
    body = "\n".join(f"{n}: {lines[n - 1]}" for n in range(first, last + 1))
    more = f"\n[lines {first}-{last} of {len(lines)}; read on with start={last + 1}]" if last < len(lines) else ""
    return f"{relative(path)} ({len(lines)} lines)\n{body}{more}"


def text_of(rel: str) -> str:
    path = resolve(rel)
    if not path.is_file() or not _is_text(path):
        raise ProjectError(f"{rel} is not a readable text file.")
    return path.read_text(encoding="utf-8", errors="replace")


def write(rel: str, content: str) -> str:
    path = resolve(rel)
    if path.is_dir():
        raise ProjectError(f"{rel} is a folder.")

    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")
    return f"{'Updated' if existed else 'Created'} {relative(path)} ({content.count(chr(10)) + 1} lines)."


def edit(rel: str, old: str, new: str, replace_all: bool) -> str:
    text = text_of(rel)
    count = text.count(old)
    if not old or count == 0:
        raise ProjectError(f"The text to replace was not found in {rel}. Read the file again and copy it exactly.")
    if count > 1 and not replace_all:
        raise ProjectError(f"The text appears {count} times in {rel}. Add surrounding lines, or set replace_all.")

    resolve(rel).write_text(text.replace(old, new), encoding="utf-8", newline="")
    return f"Edited {rel}: {count if replace_all else 1} replacement(s)."


def risks(command: str, cwd: Path) -> list[str]:
    found = [why for pattern, why in RISKY_COMMANDS if pattern.search(command)]
    base = root()
    for match in _ABSOLUTE.finditer(command):
        target = Path(match.group(1)).expanduser().resolve()
        if target != base and base not in target.parents:
            found.append(f"touches {match.group(1)} outside the workspace")
    if re.search(r"(^|[\s\"'\\/])\.\.([\\/]|\s|$)", command) and cwd == base:
        found.append("climbs out of the workspace")
    return list(dict.fromkeys(found))


def _shell(command: str) -> list[str]:
    if sys.platform == "win32":
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            raise ProjectError("PowerShell is not installed.")
        return [shell, "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/bash", "-lc", command]


def run(command: str, rel: str, timeout: int, cancel: Cancel) -> str:
    cwd = resolve(rel)
    if not cwd.is_dir():
        raise ProjectError(f"Not a folder: {rel}")

    limit = min(max(timeout, 1), MAX_TIMEOUT_SECONDS)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryFile() as out:
        process = subprocess.Popen(
            _shell(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "NO_COLOR": "1", "OV_READONLY": "1"},
            creationflags=flags,
        )
        timed_out = _wait(process, limit, cancel)
        out.seek(0)
        text = out.read().decode("utf-8", "replace")

    head = f"$ {command}\n(in {relative(cwd) or '.'}, exit {process.returncode}{', timed out' if timed_out else ''})\n"
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[: MAX_OUTPUT_CHARS // 2] + "\n...[output cut]...\n" + text[-MAX_OUTPUT_CHARS // 2 :]
    return head + (text.strip() or "(no output)")


def _wait(process: subprocess.Popen[Any], limit: int, cancel: Cancel) -> bool:
    deadline = time.monotonic() + limit
    while process.poll() is None:
        if cancel.is_set() or time.monotonic() > deadline:
            process.kill()
            process.wait()
            cancel.check()
            return True
        time.sleep(POLL_SECONDS)
    return False
