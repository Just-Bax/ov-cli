from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ov.agent.api.handler import CONTENT_TYPES, Handler, HttpError, objects, required, route
from ov.agent.api.routes.instances import screen_size
from ov.agent.api.streams import open_stream, pump, write_stream
from ov.agent.engine.export import to_markdown
from ov.agent.engine.feed import status_feed
from ov.agent.engine.files import attachments_dir, within
from ov.agent.engine.run_manager import runs
from ov.agent.storage import db
from ov.agent.storage.models import Access, FollowUp

SETTLED_PAGE = 50
DEFAULT_TURNS = 10
MAX_TURNS = 100
EXPORT_NAME_CHARS = 80
_UNSAFE_FILE_CHARS = re.compile(r"[^\w\- ]+")
MIN_SEARCH_CHARS = 3
INLINE_FILES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".log", ".csv"}


def require_thread(run_id: str) -> None:
    if db.get_thread(run_id) is None:
        raise HttpError(404, "Run not found.")


def require_run(run_id: str) -> Any:
    run = runs.get(run_id)
    if run is None:
        raise HttpError(404, "Run not found.")
    return run


@route("GET", "/api/threads")
def list_runs(h: Handler) -> dict[str, Any]:
    settled = min(max(int(h.query.get("settled", str(SETTLED_PAGE))), 1), db.RUN_LIST_LIMIT)
    open_runs = db.list_threads(settled=False)

    return {
        "active": [r for r in open_runs if "snoozedUntil" not in r],
        "snoozed": [r for r in open_runs if "snoozedUntil" in r],
        "settled": db.list_threads(settled=True, limit=settled),
        "settledTotal": db.settled_count(),
    }


@route("POST", "/api/threads")
def start_run(h: Handler) -> dict[str, str]:
    data = h.json()
    settings = db.get_preferences()
    prompt = str(data.get("prompt") or "").strip()
    attachments = objects(data, "attachments")
    if not prompt and not attachments:
        raise HttpError(400, "Describe what you need.")
    model = settings["defaultModel"]
    if not model:
        raise HttpError(400, "Pick a model first (Settings).")
    provider = settings["provider"]

    instance = str(data.get("instance") or "").strip()
    run = runs.create(
        {
            "prompt": prompt,
            "instance": instance or None,
            "attachments": attachments,
            "access": _access(data),
        },
        provider,
        model,
    )

    return {"id": run.id}


@route("DELETE", "/api/threads/([a-z0-9]+)")
def delete_run(_: Handler, run_id: str) -> dict[str, bool]:
    runs.delete(run_id)
    return {"ok": True}


@route("GET", "/api/threads/([a-z0-9]+)")
def get_run(h: Handler, run_id: str) -> str:
    return require_run(run_id).snapshot(_turns(h))


def _turns(h: Handler) -> int:
    return max(1, min(int(h.query.get("turns", str(DEFAULT_TURNS))), MAX_TURNS))


@route("GET", "/api/threads/([a-z0-9]+)/history")
def run_history(h: Handler, run_id: str) -> str:
    return require_run(run_id).history(int(required(h.query, "end")), _turns(h))


@route("GET", "/api/threads/([a-z0-9]+)/search")
def run_search(h: Handler, run_id: str) -> dict[str, list[int]]:
    query = required(h.query, "q").strip()
    if not query:
        raise HttpError(400, "Give something to find.")
    return require_run(run_id).search(query)


@route("GET", "/api/threads/([a-z0-9]+)/details")
def run_details(h: Handler, run_id: str) -> str:
    tools = {x for x in h.query.get("tools", "").split(",") if x}
    edits = {x for x in h.query.get("edits", "").split(",") if x}
    return require_run(run_id).details(tools, edits)


@route("POST", "/api/threads/([a-z0-9]+)/compact")
def compact(_: Handler, run_id: str) -> dict[str, bool]:
    require_run(run_id).compact()
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/continue")
def continue_run(_: Handler, run_id: str) -> dict[str, str]:
    require_thread(run_id)
    return {"id": runs.continue_in_new(run_id).id}


@route("POST", "/api/threads/([a-z0-9]+)/branch")
def branch(h: Handler, run_id: str) -> dict[str, str]:
    before = h.json().get("before")
    if before is not None and not isinstance(before, str):
        raise HttpError(400, "before must be a message id or null.")
    return {"id": runs.branch(run_id, before).id}


@route("POST", "/api/threads/([a-z0-9]+)/retry-branch")
def retry_branch(h: Handler, run_id: str) -> dict[str, str]:
    return {"id": runs.retry_as_branch(run_id, required(h.json(), "itemId")).id}


@route("POST", "/api/threads/([a-z0-9]+)/aside")
def aside(h: Handler, run_id: str) -> dict[str, str]:
    data = h.json()
    text, files = str(data.get("text", "")), objects(data, "files")
    if not text.strip() and not files:
        raise HttpError(400, "Write what to ask in the aside.")
    return {"id": runs.aside(run_id, required(data, "id"), text, files).id}


@route("GET", "/api/threads/([a-z0-9]+)/branches")
def branches(_: Handler, run_id: str) -> dict[str, Any]:
    require_thread(run_id)
    return {"branches": db.child_threads(run_id)}


@route("POST", "/api/threads/([a-z0-9]+)/bring-back/draft")
def bring_back_draft(_: Handler, run_id: str) -> dict[str, str]:
    return {"text": require_run(run_id).bring_back_draft()}


@route("POST", "/api/threads/([a-z0-9]+)/bring-back")
def bring_back(h: Handler, run_id: str) -> dict[str, bool]:
    runs.bring_back(run_id, str(required(h.json(), "text")))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/from-findings")
def from_findings(_: Handler, run_id: str) -> dict[str, str]:
    return {"id": runs.from_findings(run_id).id}


@route("GET", "/api/threads/([a-z0-9]+)/findings")
def findings(_: Handler, run_id: str) -> dict[str, Any]:
    require_thread(run_id)
    return {"findings": db.list_findings(run_id)}


@route("POST", "/api/threads/([a-z0-9]+)/findings")
def add_finding(h: Handler, run_id: str) -> dict[str, Any]:
    return require_run(run_id).save_finding(str(required(h.json(), "text")))


@route("POST", "/api/threads/([a-z0-9]+)/findings/([0-9]+)")
def edit_finding(h: Handler, run_id: str, finding_id: str) -> dict[str, bool]:
    text = str(required(h.json(), "text")).strip()
    if not text:
        raise HttpError(400, "A finding needs some text.")
    db.update_finding(run_id, int(finding_id), text)
    require_run(run_id).push_live({"type": "findings"})
    return {"ok": True}


@route("DELETE", "/api/threads/([a-z0-9]+)/findings/([0-9]+)")
def delete_finding(_: Handler, run_id: str, finding_id: str) -> dict[str, bool]:
    db.delete_finding(run_id, int(finding_id))
    require_run(run_id).push_live({"type": "findings"})
    return {"ok": True}


@route("GET", "/api/search")
def search_threads(h: Handler) -> dict[str, Any]:
    query = required(h.query, "q").strip()
    if len(query) < MIN_SEARCH_CHARS:
        raise HttpError(400, f"Search for at least {MIN_SEARCH_CHARS} characters.")
    return {"threads": db.search_threads(query)}


@route("POST", "/api/threads/([a-z0-9]+)/pin")
def pin(h: Handler, run_id: str) -> dict[str, bool]:
    require_thread(run_id)

    pinned = h.json().get("pinned")
    if not isinstance(pinned, bool):
        raise HttpError(400, "Give pinned as true or false.")

    db.set_pinned(run_id, pinned)
    status_feed.publish({"kind": "list"})
    return {"ok": True}


def _not_waiting(run_id: str, action: str) -> None:
    thread = db.get_thread(run_id)
    if thread is not None and thread["status"] == "waiting":
        raise HttpError(400, f"This thread is waiting for you. Answer it before {action}.")


@route("POST", "/api/threads/([a-z0-9]+)/snooze")
def snooze(h: Handler, run_id: str) -> dict[str, bool]:
    require_thread(run_id)

    until = h.json().get("until")
    if until is not None and not isinstance(until, int):
        raise HttpError(400, "Give until as a time in milliseconds, or null.")
    if until is not None:
        _not_waiting(run_id, "snoozing")

    db.set_snoozed(run_id, until)
    status_feed.publish({"kind": "list"})
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/seen")
def seen(_: Handler, run_id: str) -> dict[str, bool]:
    require_thread(run_id)
    db.set_seen(run_id)
    status_feed.publish({"kind": "list"})
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/settle")
def settle(h: Handler, run_id: str) -> dict[str, bool]:
    require_thread(run_id)

    settled = h.json().get("settled")
    if not isinstance(settled, bool):
        raise HttpError(400, "Give settled as true or false.")
    if settled:
        _not_waiting(run_id, "settling")

    db.set_settled(run_id, settled)
    status_feed.publish({"kind": "list"})
    return {"ok": True}


@route("GET", "/api/status-events")
def status_events(h: Handler) -> None:
    channel, unsubscribe = status_feed.subscribe()
    try:
        open_stream(h)
        pump(h, channel, lambda change: write_stream(h, f"data: {json.dumps(change)}\n\n"))
    except OSError:
        pass
    finally:
        unsubscribe()


@route("GET", "/api/threads/([a-z0-9]+)/events")
def run_events(h: Handler, run_id: str) -> None:
    run = require_run(run_id)
    last = int(required(h.query, "after"))
    channel, unsubscribe, backlog = run.resume(last)

    def emit(stored: dict[str, Any]) -> None:
        nonlocal last
        write_stream(h, f"id: {stored['seq']}\ndata: {json.dumps(stored)}\n\n")
        last = stored["seq"]

    def emit_unseen(stored: dict[str, Any]) -> None:
        if stored.get("live") or stored["seq"] > last:
            emit(stored)

    try:
        open_stream(h)
        for stored in backlog:
            emit(stored)
        pump(h, channel, emit_unseen)
    except OSError:
        pass
    finally:
        unsubscribe()


@route("POST", "/api/threads/([a-z0-9]+)/answer")
def answer(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    answers = data.get("answers")
    if not isinstance(answers, list) or not all(isinstance(a, str) for a in answers):
        raise HttpError(400, "answers must be a list of strings.")
    require_run(run_id).answer(required(data, "questionId"), answers, str(data.get("note") or ""))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/login")
def run_login(h: Handler, run_id: str) -> dict[str, Any]:
    data = h.json()
    run = require_run(run_id)
    login_id = required(data, "loginId")
    token = str(data.get("token") or "").strip()
    return run.login(login_id, bool(data.get("skip")), token, screen_size(data), bool(data.get("remember")))


@route("POST", "/api/threads/([a-z0-9]+)/message")
def message(h: Handler, run_id: str) -> dict[str, bool]:
    data = h.json()
    files = objects(data, "files")
    mode = required(data, "mode")
    if mode not in FollowUp:
        raise HttpError(400, f"mode must be one of {', '.join(FollowUp)}.")

    require_run(run_id).follow_up(required(data, "id"), str(data.get("text", "")), files, mode == FollowUp.STEER)
    db.set_settled(run_id, False)
    db.set_snoozed(run_id, None)
    status_feed.publish({"kind": "list"})
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/grids/([A-Za-z0-9_]+)/rerun")
def rerun_grid(_: Handler, run_id: str, grid_id: str) -> dict[str, bool]:
    require_run(run_id).rerun_grid(grid_id)
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/grids/([A-Za-z0-9_]+)/revert")
def revert_grid(_: Handler, run_id: str, grid_id: str) -> dict[str, bool]:
    require_run(run_id).revert_grid(grid_id)
    db.set_settled(run_id, False)
    db.set_snoozed(run_id, None)
    status_feed.publish({"kind": "list"})
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/title")
def rename(h: Handler, run_id: str) -> dict[str, bool]:
    require_run(run_id).rename(required(h.json(), "title"))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/retry")
def retry(h: Handler, run_id: str) -> dict[str, bool]:
    require_run(run_id).retry(required(h.json(), "itemId"))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/queued/([^/]+)/send")
def send_queued(_: Handler, run_id: str, message_id: str) -> dict[str, bool]:
    require_run(run_id).send_queued(message_id)
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/queued/([^/]+)/text")
def edit_queued(h: Handler, run_id: str, message_id: str) -> dict[str, bool]:
    require_run(run_id).edit_queued(message_id, str(h.json().get("text", "")))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/queued/([^/]+)/move")
def move_queued(h: Handler, run_id: str, message_id: str) -> dict[str, bool]:
    before = h.json().get("before")
    if before is not None and not isinstance(before, str):
        raise HttpError(400, "before must be a queued message id or null.")
    require_run(run_id).move_queued(message_id, before)
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/queue/resume")
def resume_queue(_: Handler, run_id: str) -> dict[str, bool]:
    require_run(run_id).resume_queue()
    return {"ok": True}


@route("DELETE", "/api/threads/([a-z0-9]+)/queued/([^/]+)")
def remove_queued(_: Handler, run_id: str, message_id: str) -> dict[str, bool]:
    require_run(run_id).remove_queued(message_id)
    return {"ok": True}


@route("GET", "/api/threads/([a-z0-9]+)/cost")
def run_cost(_: Handler, run_id: str) -> dict[str, Any]:
    require_thread(run_id)
    return db.thread_cost(run_id)


@route("GET", "/api/threads/([a-z0-9]+)/export")
def export_run(h: Handler, run_id: str) -> None:
    run = require_run(run_id)
    name = _UNSAFE_FILE_CHARS.sub("", run.state["summary"]["title"]).strip()[:EXPORT_NAME_CHARS] or run_id

    h.send(
        200,
        to_markdown(run.state).encode("utf-8"),
        "text/markdown; charset=utf-8",
        extra={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}.md"},
    )


@route("GET", "/api/threads/([a-z0-9]+)/files/([^/]+)")
def run_file(h: Handler, run_id: str, name: str) -> None:
    require_thread(run_id)
    path = within(attachments_dir(run_id), Path(name).name)
    if not path.is_file():
        raise HttpError(404, "File not found.")

    suffix = path.suffix.lower()
    if suffix in INLINE_FILES:
        content_type, disposition = CONTENT_TYPES[suffix], "inline"
    else:
        content_type, disposition = "application/octet-stream", "attachment"

    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(path.name)}"}
    if suffix != ".pdf":
        headers["Content-Security-Policy"] = "sandbox"

    h.send(200, path.read_bytes(), content_type, extra=headers)


def _access(data: dict[str, Any]) -> Access:
    value = required(data, "access")
    if value not in set(Access):
        raise HttpError(400, f"Unknown access mode {value}.")
    access = Access(value)
    runs.require_access(access)
    return access


@route("POST", "/api/threads/([a-z0-9]+)/access")
def access(h: Handler, run_id: str) -> dict[str, bool]:
    require_run(run_id).set_access(_access(h.json()))
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/cancel")
def cancel(_: Handler, run_id: str) -> dict[str, bool]:
    require_run(run_id).stop()
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/tools/([A-Za-z0-9_\\-]+)/background")
def background_tool(_: Handler, run_id: str, tool_id: str) -> dict[str, bool]:
    require_run(run_id).move_to_background(tool_id)
    return {"ok": True}


@route("POST", "/api/threads/([a-z0-9]+)/tools/([A-Za-z0-9_\\-]+)/stop")
def stop_tool(_: Handler, run_id: str, tool_id: str) -> dict[str, bool]:
    require_run(run_id).stop_tool(tool_id)
    return {"ok": True}
