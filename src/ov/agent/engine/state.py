from __future__ import annotations

from collections.abc import Callable
from typing import Any

State = dict[str, Any]
Stored = dict[str, Any]

MARK_LABEL_CHARS = 160
WINDOWED = ("items", "chat", "tools", "changes", "questions", "logins", "edits")
TOOL_DETAIL = ("input", "output")
EDIT_DETAIL = ("before", "after")


def empty_state(summary: dict[str, Any], write: bool) -> State:
    return {
        "summary": summary,
        "items": [],
        "tools": [],
        "changes": [],
        "edits": [],
        "questions": [],
        "logins": [],
        "chat": [],
        "writeAccess": write,
        "queued": [],
        "claude": {"session": None, "turns": {}, "spent": 0.0},
    }


def _upsert(items: list[dict[str, Any]], new: dict[str, Any], merge: bool = False) -> None:
    for index, existing in enumerate(items):
        if existing["id"] == new["id"]:
            items[index] = {**existing, **new} if merge else new
            return
    items.append(new)


def _add_item(state: State, kind: str, item_id: str) -> None:
    if not any(x["kind"] == kind and x["id"] == item_id for x in state["items"]):
        state["items"].append({"kind": kind, "id": item_id})


def _without(messages: list[dict[str, Any]], message_id: str) -> list[dict[str, Any]]:
    return [m for m in messages if m["id"] != message_id]


def _on_status(state: State, stored: Stored) -> None:
    event = stored["event"]
    state["summary"] = {**state["summary"], "status": event["status"], "updatedAt": stored["ts"]}
    if event["status"] == "error":
        state["error"] = event["error"]


def _on_meta(state: State, stored: Stored) -> None:
    event = stored["event"]
    for key in ("title", "instance", "caseKey"):
        if event.get(key) is not None:
            state["summary"][key] = event[key]
    if event.get("caseUrl"):
        state["caseUrl"] = event["caseUrl"]
    anchor = event.get("claude")
    if anchor:
        if anchor["session"] != state["claude"]["session"]:
            state["claude"]["spent"] = 0.0
        state["claude"]["session"] = anchor["session"]
        if anchor.get("turn"):
            state["claude"]["turns"][anchor["turn"]] = anchor
        if anchor.get("spent") is not None:
            state["claude"]["spent"] = anchor["spent"]


def _on_tool(state: State, stored: Stored) -> None:
    tool = stored["event"]["tool"]
    _upsert(state["tools"], tool, merge=True)
    _add_item(state, "tool", tool["id"])


def _on_text(state: State, stored: Stored) -> None:
    event = stored["event"]
    for message in state["chat"]:
        if message["id"] == event["messageId"]:
            message["text"] += event["delta"]
            break
    else:
        state["chat"].append(
            {"id": event["messageId"], "role": "assistant", "text": event["delta"], "ts": stored["ts"]}
        )
    _add_item(state, "text", event["messageId"])


def _on_message(state: State, stored: Stored) -> None:
    event = stored["event"]
    for message in state["chat"]:
        if message["id"] == event["messageId"]:
            message["text"] = event["text"]
            break
    else:
        message = {
            "id": event["messageId"],
            "role": "assistant",
            "text": event["text"],
            "ts": event.get("ts", stored["ts"]),
        }
        state["chat"].append(message)
    if event.get("links"):
        message["links"] = event["links"]
    _add_item(state, "text", event["messageId"])


def _on_user(state: State, stored: Stored) -> None:
    message = stored["event"]["message"]
    state["queued"] = _without(state["queued"], message["id"])
    state["chat"] = [*_without(state["chat"], message["id"]), message]
    _add_item(state, "user", message["id"])


def _on_outcome(state: State, stored: Stored) -> None:
    state["outcome"], state["outcomeId"] = stored["event"]["outcome"], f"o{stored['seq']}"
    _add_item(state, "outcome", state["outcomeId"])


def _upserter(kind: str, collection: str) -> Callable[[State, Stored], None]:
    def apply(state: State, stored: Stored) -> None:
        entry = stored["event"][kind]
        _upsert(state[collection], entry)
        _add_item(state, kind, entry["id"])

    return apply


def _on_edit(state: State, stored: Stored) -> None:
    _upsert(state["edits"], stored["event"]["edit"])


def _on_queued(state: State, stored: Stored) -> None:
    message = stored["event"]["message"]
    state["queued"] = [*_without(state["queued"], message["id"]), message]


def _on_unqueue(state: State, stored: Stored) -> None:
    state["queued"] = _without(state["queued"], stored["event"]["id"])


def _on_rewind(state: State, stored: Stored) -> None:
    item_id = stored["event"]["itemId"]
    index = next((i for i, x in enumerate(state["items"]) if x["kind"] == "user" and x["id"] == item_id), -1)
    if index < 0:
        return

    state["items"] = state["items"][:index]
    keep = {f"{x['kind']}:{x['id']}" for x in state["items"]}
    state["chat"] = [m for m in state["chat"] if f"{'user' if m['role'] == 'user' else 'text'}:{m['id']}" in keep]
    if not (state.get("outcomeId") and f"outcome:{state['outcomeId']}" in keep):
        state.pop("outcome", None)
        state.pop("outcomeId", None)


def _on_access(state: State, stored: Stored) -> None:
    state["writeAccess"] = stored["event"]["write"]


def _on_browser(state: State, stored: Stored) -> None:
    state["browser"] = {**state.get("browser", {}), **stored["event"]["browser"]}


_REDUCERS: dict[str, Callable[[State, Stored], None]] = {
    "status": _on_status,
    "meta": _on_meta,
    "tool": _on_tool,
    "text": _on_text,
    "message": _on_message,
    "user": _on_user,
    "change": _upserter("change", "changes"),
    "edit": _on_edit,
    "outcome": _on_outcome,
    "question": _upserter("question", "questions"),
    "login": _upserter("login", "logins"),
    "queued": _on_queued,
    "unqueue": _on_unqueue,
    "rewind": _on_rewind,
    "access": _on_access,
    "browser": _on_browser,
}


def reduce(state: State, stored: Stored) -> State:
    reducer = _REDUCERS.get(stored["event"]["type"])
    if reducer is not None:
        reducer(state, stored)
    return state


def _brief(entry: dict[str, Any], detail: tuple[str, ...]) -> dict[str, Any]:
    if not any(entry.get(key) for key in detail):
        return entry
    return {**{k: v for k, v in entry.items() if k not in detail}, "lazy": True}


def _turn_starts(items: list[dict[str, Any]]) -> list[int]:
    starts = [i for i, item in enumerate(items) if item["kind"] == "user"]
    return starts if starts and starts[0] == 0 else [0, *starts]


def _agent_label(state: State, part: list[dict[str, Any]], chat: dict[str, dict[str, Any]]) -> str:
    texts = [chat[x["id"]]["text"].strip() for x in part if x["kind"] == "text" and x["id"] in chat]
    changes = {c["id"]: c["title"] for c in state["changes"]}
    titles = [changes[x["id"]] for x in part if x["kind"] == "change" and x["id"] in changes]
    return ("\n\n".join(t for t in texts if t) or "\n".join(titles) or "Working")[:MARK_LABEL_CHARS]


def outline(state: State, end: int) -> list[dict[str, Any]]:
    items = state["items"]
    chat = {m["id"]: m for m in state["chat"]}
    starts = [s for s in _turn_starts(items) if s < end]
    marks: list[dict[str, Any]] = []
    for index, start in enumerate(starts):
        stop = starts[index + 1] if index + 1 < len(starts) else end
        part = items[start:stop]
        if part and part[0]["kind"] == "user" and part[0]["id"] in chat:
            label = chat[part[0]["id"]]["text"][:MARK_LABEL_CHARS]
            marks.append({"kind": "user", "start": start, "label": label})
        rest = [x for x in part if x["kind"] != "user"]
        if rest:
            marks.append({"kind": "agent", "start": start, "label": _agent_label(state, rest, chat)})
    return marks


def window(state: State, end: int, turns: int) -> State:
    items = state["items"]
    starts = [s for s in _turn_starts(items) if s < end]
    start = starts[-turns] if len(starts) > turns else 0
    part = items[start:end]
    keys = {(x["kind"], x["id"]) for x in part}
    return {
        "items": part,
        "start": start,
        "chat": [m for m in state["chat"] if ("user" if m["role"] == "user" else "text", m["id"]) in keys],
        "tools": [_brief(t, TOOL_DETAIL) for t in state["tools"] if ("tool", t["id"]) in keys],
        "changes": [c for c in state["changes"] if ("change", c["id"]) in keys],
        "questions": [q for q in state["questions"] if ("question", q["id"]) in keys],
        "logins": [x for x in state["logins"] if ("login", x["id"]) in keys],
        "outline": outline(state, start),
    }


def snapshot(state: State, turns: int) -> State:
    return {
        **{k: v for k, v in state.items() if k not in WINDOWED and k != "claude"},
        **window(state, len(state["items"]), turns),
        "edits": [_brief(e, EDIT_DETAIL) for e in state["edits"]],
    }


def details(state: State, tool_ids: set[str], edit_ids: set[str]) -> dict[str, Any]:
    return {
        "tools": {t["id"]: {k: t.get(k) for k in TOOL_DETAIL} for t in state["tools"] if t["id"] in tool_ids},
        "edits": {e["id"]: {k: e.get(k) for k in EDIT_DETAIL} for e in state["edits"] if e["id"] in edit_ids},
    }


def _searchable(state: State) -> dict[tuple[str, str], str]:
    texts: dict[tuple[str, str], str] = {}
    for message in state["chat"]:
        texts[("user" if message["role"] == "user" else "text", message["id"])] = message["text"]
    for change in state["changes"]:
        texts[("change", change["id"])] = " ".join(
            change.get(k) or "" for k in ("title", "what", "why", "how", "after")
        )
    for question in state["questions"]:
        texts[("question", question["id"])] = f"{question['question']} {question.get('answer') or ''}"
    outcome = state.get("outcome")
    if outcome and state.get("outcomeId"):
        parts = [outcome.get("reply") or "", *(f"{i['title']} {i['summary']}" for i in outcome.get("issues") or [])]
        texts[("outcome", state["outcomeId"])] = " ".join(parts)
    return texts


def search(state: State, query: str) -> list[int]:
    wanted = query.casefold()
    texts = _searchable(state)
    return [
        index
        for index, item in enumerate(state["items"])
        if wanted in texts.get((item["kind"], item["id"]), "").casefold()
    ]
