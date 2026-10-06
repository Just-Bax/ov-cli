from __future__ import annotations

import base64
import json
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .cancel import Cancel
from .ovproc import find_instance, run_ov
from .runfiles import describe, html_to_text, unique_path

TRACKOR_HOST = "trackor.onevizion.com"
CASE_TYPE = "Cases"
FIELD_BATCH = 40
FETCH_WORKERS = 6
MAX_FIELD_CHARS = 6000
MAX_CASE_CHARS = 90_000
MAX_CHAT_PAGES = 20
CHAT_PAGE_SIZE = 100
ERROR_CHARS = 2000
OUTPUT_PREVIEW_CHARS = 300

FILE_TYPES = {"ELECTRONIC_FILE", "MULTIPLE_EFILES"}
SKIP_FIELDS = {
    "C_EMAIL_MESSAGE",
    "C_ATTACHMENT2",
    "C_NOTIFY_COMMENT",
    "C_NOTIFY_GROUP",
    "C_NOTIFY_ICC",
    "C_NOTIFY_OWNER",
    "C_NOTIFY_RESLN",
    "C_NOTIFY_STATUS",
    "C_FOLLOW",
    "C_UNFOLLOW",
    "C_EXCLUDE_ME_IN_MY_ACTIVE_CASE",
}
KEY_FIELDS = {"TRACKOR_ID", "TRACKOR_KEY", "XITOR_KEY"}
EMPTY_VALUES = (None, "", "0")

CASE_ONLY = re.compile(r"^\s*(?:case\s*)?#?(\d{5,8})\s*$", re.IGNORECASE)
TRACKOR_LINK = re.compile(r"^\s*https?://trackor\.onevizion\.com/\S*[?&]id=(\d{9,})\S*\s*$")

_schema: list[dict[str, Any]] | None = None
_schema_lock = threading.Lock()


class NeedsLogin(Exception):
    def __init__(self, host: str = TRACKOR_HOST) -> None:
        super().__init__(f"Not signed in to {host}")
        self.host = host


class CaseError(Exception):
    pass


def case_ref(prompt: str) -> str | None:
    if TRACKOR_LINK.match(prompt):
        return prompt.strip()
    only = CASE_ONLY.match(prompt)
    return only.group(1) if only else None


def form_url(trackor_id: int | str, host: str = TRACKOR_HOST) -> str:
    return f"https://{host}/form/ConfigAppForm.do?id={trackor_id}"


def _parse_ref(ref: str) -> tuple[str | None, str | None]:
    text = ref.strip()
    found = re.search(r"[?&]id=(\d{9,})", text)
    if found:
        return None, found.group(1)
    key = re.search(r"\b(\d{4,8})\b", text)
    return (key.group(1), None) if key else (None, None)


class _Trackor:
    def __init__(self, cancel: Cancel) -> None:
        found = find_instance(TRACKOR_HOST)
        if found is None:
            raise NeedsLogin
        self.alias = found["alias"]
        self.cancel = cancel

    def run(self, args: list[str]) -> Any:
        result = run_ov(["-i", self.alias, *args, "--json"], cancel=self.cancel)
        if result.is_auth:
            raise NeedsLogin
        if result.code != 0:
            raise CaseError(result.message[:ERROR_CHARS] or f"ov exited {result.code}")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            raise CaseError(f"ov returned non-JSON output: {result.stdout[:OUTPUT_PREVIEW_CHARS]}") from None

    def get(self, path: str, *query: str) -> Any:
        args = ["request", "GET", path]
        for item in query:
            args += ["-q", item]
        return self.run(args)

    def download(self, blob_id: int, target: Path) -> None:
        result = run_ov(
            [
                "-i",
                self.alias,
                "request",
                "GET",
                f"/../efiles/EFileGetBlobFromDb.do?id={blob_id}",
                "--out",
                str(target),
            ],
            cancel=self.cancel,
        )
        if result.code != 0:
            raise CaseError(f"Downloading {target.name} failed: {result.message[:ERROR_CHARS]}")


def _case_schema(trackor: _Trackor) -> list[dict[str, Any]]:
    global _schema
    with _schema_lock:
        if _schema is None:
            _schema = trackor.get(f"/v3/trackor_types/{CASE_TYPE}")
        return _schema


def _locate(trackor: _Trackor, key: str | None, trackor_id: str | None) -> tuple[str, int]:
    if trackor_id:
        head = trackor.get(f"/v3/trackors/{trackor_id}", "fields=XITOR_KEY")
        return str(head["TRACKOR_KEY"]), int(trackor_id)

    rows = trackor.get(f"/v3/trackor_types/{CASE_TYPE}/trackors", "fields=XITOR_KEY", f"XITOR_KEY={key}")
    hit = next((r for r in rows if str(r["TRACKOR_KEY"]) == key), None)
    if hit is None:
        raise CaseError(f"Case {key} not found on {TRACKOR_HOST}.")
    return key, int(hit["TRACKOR_ID"])


def _fetch(
    trackor: _Trackor, tid: int, text_fields: list[str], file_fields: list[str]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    batches = [text_fields[i : i + FIELD_BATCH] for i in range(0, len(text_fields), FIELD_BATCH)]
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        parts = list(pool.map(lambda b: trackor.get(f"/v3/trackors/{tid}", f"fields={','.join(b)}"), batches))
        files = trackor.get(f"/v3/trackors/{tid}", f"fields={','.join(file_fields)}")
        chats = trackor.get("/v3/chats", f"trackor_id={tid}")

    row: dict[str, Any] = {}
    for part in parts:
        row.update(part)
    return row, files, chats


def _field_texts(row: dict[str, Any], labels: dict[str, str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for name, value in row.items():
        if value in EMPTY_VALUES or name in KEY_FIELDS:
            continue
        text = html_to_text(value) if isinstance(value, str) else json.dumps(value)
        if len(text) > MAX_FIELD_CHARS:
            text = text[:MAX_FIELD_CHARS] + "\n...[truncated]"
        if text:
            fields[f"{labels.get(name, name)} [{name}]"] = text
    return fields


def _efiles(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def _file_attachments(
    files: dict[str, Any], file_fields: list[str], labels: dict[str, str], attach_dir: Path
) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for name in file_fields:
        for item in _efiles(files.get(name)):
            if not item.get("data") or not item.get("file_name"):
                continue
            target = unique_path(attach_dir, item["file_name"])
            target.write_bytes(base64.b64decode(item["data"]))
            attachments.append(describe(target, labels.get(name, name)))
    return attachments


def load_case(ref: str, work_dir: Path, cancel: Cancel) -> dict[str, Any]:
    key, trackor_id = _parse_ref(ref)
    if not key and not trackor_id:
        raise CaseError(f'Cannot find a case number in "{ref}".')

    trackor = _Trackor(cancel)
    case_key, tid = _locate(trackor, key, trackor_id)

    schema = _case_schema(trackor)
    text_fields = [f["name"] for f in schema if f["data_type"] not in FILE_TYPES and f["name"] not in SKIP_FIELDS]
    file_fields = [f["name"] for f in schema if f["data_type"] in FILE_TYPES]
    labels = {f["name"]: f.get("label") or f["name"] for f in schema}
    row, files, chats = _fetch(trackor, tid, text_fields, file_fields)

    attach_dir = work_dir / "attachments"
    attach_dir.mkdir(parents=True, exist_ok=True)
    attachments = _file_attachments(files, file_fields, labels, attach_dir)
    chat, downloads = _read_chats(trackor, chats, attach_dir)
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        attachments += pool.map(lambda download: download(), downloads)
    chat.sort(key=lambda m: m["ts"])

    return {
        "key": case_key,
        "trackorId": tid,
        "url": form_url(tid),
        "title": str(row.get("C_TITLE") or ""),
        "website": str(row["C_WEBSITE"]).strip() if row.get("C_WEBSITE") else None,
        "fields": _field_texts(row, labels),
        "chat": chat,
        "attachments": attachments,
    }


def _reserve(attach_dir: Path, name: str) -> Path:
    target = unique_path(attach_dir, name)
    target.write_bytes(b"")
    return target


def _chat_message(
    trackor: _Trackor, message: dict[str, Any], attach_dir: Path, downloads: list[Callable[[], dict[str, Any]]]
) -> dict[str, Any]:
    names = []
    for item in message.get("files") or []:
        target = _reserve(attach_dir, item["file_name"])
        names.append(target.name)
        downloads.append(_downloader(trackor, item["blob_data_id"], target, message["ts"]))
    return {
        "user": message.get("user_name") or "",
        "ts": message["ts"],
        "text": html_to_text(message.get("text") or ""),
        "files": names,
    }


def _read_chats(
    trackor: _Trackor, chats: list[dict[str, Any]], attach_dir: Path
) -> tuple[list[dict[str, Any]], list[Callable[[], dict[str, Any]]]]:
    chat: list[dict[str, Any]] = []
    downloads: list[Callable[[], dict[str, Any]]] = []
    for room in chats:
        cursor = None
        for _ in range(MAX_CHAT_PAGES):
            query = [f"per_page={CHAT_PAGE_SIZE}", *([f"before_cursor={cursor}"] if cursor else [])]
            page = trackor.get(f"/v3/chats/{room['chat_id']}/messages", *query)
            chat += [_chat_message(trackor, message, attach_dir, downloads) for message in page.get("data") or []]
            cursor = page.get("before_cursor")
            if not page.get("hasBefore") or not cursor:
                break
    return chat, downloads


def _downloader(trackor: _Trackor, blob_id: int, target: Path, ts: str) -> Callable[[], dict[str, Any]]:
    def fetch() -> dict[str, Any]:
        trackor.download(blob_id, target)
        return describe(target, f"chat {ts}")

    return fetch


def render(bundle: dict[str, Any], work_dir: Path) -> str:
    website = bundle["website"]
    lines = [
        f"# Case {bundle['key']}: {bundle['title']}",
        f"Trackor link: {bundle['url']}",
        f"Affected instance (C_WEBSITE): {website}"
        if website
        else "Affected instance: not set on the case, find it from the text.",
        "",
        "## Fields",
    ]
    for name, value in bundle["fields"].items():
        lines.append(f"### {name}\n{value}" if "\n" in value else f"- {name}: {value}")
    if bundle["chat"]:
        lines += ["", "## Chat (oldest first)"]
        for message in bundle["chat"]:
            files = f" [files: {', '.join(message['files'])}]" if message["files"] else ""
            lines.append(f"- {message['ts']} {message['user']}: {message['text']}{files}")
    lines += ["", "## Attachments (open each with run_read)"]
    lines += [f"- {a['name']} ({a['kind']}, {a['size']} bytes, from {a['source']})" for a in bundle["attachments"]] or [
        "none"
    ]

    text = "\n".join(lines)
    (work_dir / "case.md").write_text(text, encoding="utf-8")
    if len(text) > MAX_CASE_CHARS:
        return text[:MAX_CASE_CHARS] + "\n\n[case text truncated; full copy in case.md, use run_read]"
    return text
