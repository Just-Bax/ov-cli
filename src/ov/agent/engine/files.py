from __future__ import annotations

import html
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from ov.core.paths import agent_dir

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
TEXT_EXTS = {
    ".txt",
    ".log",
    ".csv",
    ".json",
    ".xml",
    ".sql",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".md",
    ".yaml",
    ".yml",
}
MAX_NAME_CHARS = 120
ATTACHMENTS = "attachments"

_UNSAFE_NAME = re.compile(r"[^\w.\- ]+")
_RUN_ID = re.compile(r"^[a-z0-9]+$")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)(\..*)?$", re.IGNORECASE)


def run_dir(run_id: str) -> Path:
    if not _RUN_ID.match(run_id):
        raise ValueError(f"Bad run id: {run_id}")
    return agent_dir("runs", run_id)


def attachments_dir(run_id: str) -> Path:
    return agent_dir("runs", run_id, ATTACHMENTS)


def uploads_dir() -> Path:
    return agent_dir("uploads")


def within(root: Path, rel: str) -> Path:
    base = root.resolve()
    resolved = (base / rel).resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError(f"Path escapes {base}: {rel}")
    return resolved


def safe_name(name: str) -> str:
    cleaned = _UNSAFE_NAME.sub("_", Path(name).name)[:MAX_NAME_CHARS].strip().rstrip(". ")
    if _RESERVED.match(cleaned):
        cleaned = f"_{cleaned}"
    return cleaned or "file"


def unique_path(directory: Path, name: str) -> Path:
    candidate = directory / safe_name(name)
    stem, suffix = candidate.stem, candidate.suffix
    index = 2

    while candidate.exists():
        candidate = directory / f"{stem}-{index}{suffix}"
        index += 1

    return candidate


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXTS or ext == ".bmp":
        return "image"
    if ext in (".eml", ".msg"):
        return "email"
    if ext == ".pdf":
        return "pdf"
    if ext in TEXT_EXTS:
        return "text"
    return "other"


def image_mime(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    return "image/jpeg" if ext == "jpg" else f"image/{ext}"


def html_to_text(value: str) -> str:
    text = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|tr|h\d)>", "\n", text, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def describe(path: Path, source: str) -> dict[str, Any]:
    kind = kind_of(path.name)
    if kind == "email" and path.suffix.lower() == ".eml":
        _expand_email(path)

    return {
        "name": path.name,
        "path": str(path),
        "source": source,
        "size": path.stat().st_size,
        "kind": kind,
    }


def _expand_email(path: Path) -> None:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    body = message.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    if body is not None and body.get_content_type() == "text/html":
        text = html_to_text(text)

    lines = [f"{header}: {message.get(header, '')}" for header in ("From", "To", "Cc", "Date")]
    lines += [f"Subject: {message.get('Subject', '')}", "", text.strip()]

    for part in message.iter_attachments():
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        target = unique_path(path.parent, part.get_filename() or "email-attachment")
        target.write_bytes(payload)
        lines += ["", f"[attachment saved: {target.name}]"]

    Path(f"{path}.txt").write_text("\n".join(lines), encoding="utf-8")
