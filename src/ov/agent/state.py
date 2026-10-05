from __future__ import annotations

from collections.abc import Callable
from typing import Any

State = dict[str, Any]
Stored = dict[str, Any]


def empty_state(summary: dict[str, Any], data: dict[str, Any]) -> State:
    return {
        "summary": summary,
        "input": data,
        "items": [],
        "tools": [],
        "changes": [],
        "questions": [],
        "logins": [],
        "chat": [],
        "writeAccess": bool(data.get("allowWrite")),
        "queued": [],
        "ratings": {},
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


def _on_rate(state: State, stored: Stored) -> None:
    event = stored["event"]
    if event["rating"]:
        state["ratings"][event["turnId"]] = {"rating": event["rating"], "note": event["note"]}
    else:
        state["ratings"].pop(event["turnId"], None)


def _on_access(state: State, stored: Stored) -> None:
    state["writeAccess"] = stored["event"]["write"]


_REDUCERS: dict[str, Callable[[State, Stored], None]] = {
    "status": _on_status,
    "meta": _on_meta,
    "tool": _on_tool,
    "text": _on_text,
    "user": _on_user,
    "change": _upserter("change", "changes"),
    "outcome": _on_outcome,
    "question": _upserter("question", "questions"),
    "login": _upserter("login", "logins"),
    "queued": _on_queued,
    "unqueue": _on_unqueue,
    "rewind": _on_rewind,
    "rate": _on_rate,
    "access": _on_access,
}


def reduce(state: State, stored: Stored) -> State:
    reducer = _REDUCERS.get(stored["event"]["type"])
    if reducer is not None:
        reducer(state, stored)
    return state
