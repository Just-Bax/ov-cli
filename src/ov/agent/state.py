from __future__ import annotations

from typing import Any

# Mirrors web/shared/reduce.ts; keep the two in sync.


def empty_state(summary: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
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


def _add_item(state: dict[str, Any], kind: str, item_id: str) -> None:
    if not any(x["kind"] == kind and x["id"] == item_id for x in state["items"]):
        state["items"].append({"kind": kind, "id": item_id})


def reduce(state: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    event, ts, seq = stored["event"], stored["ts"], stored["seq"]
    kind = event.get("type")

    if kind == "status":
        state["summary"] = {**state["summary"], "status": event["status"], "updatedAt": ts}
        if event["status"] == "error":
            state["error"] = event.get("error")
    elif kind == "meta":
        for key in ("title", "instance"):
            if event.get(key) is not None:
                state["summary"][key] = event[key]
    elif kind == "tool":
        _upsert(state["tools"], event["tool"], merge=True)
        _add_item(state, "tool", event["tool"]["id"])
    elif kind == "text":
        _append_text(state, event, ts)
    elif kind == "user":
        message = event["message"]
        state["queued"] = [m for m in state["queued"] if m["id"] != message["id"]]
        state["chat"] = [m for m in state["chat"] if m["id"] != message["id"]] + [message]
        _add_item(state, "user", message["id"])
    elif kind == "change":
        _upsert(state["changes"], event["change"])
        _add_item(state, "change", event["change"]["id"])
    elif kind == "outcome":
        state["outcome"], state["outcomeId"] = event["outcome"], f"o{seq}"
        _add_item(state, "outcome", state["outcomeId"])
    elif kind == "question":
        _upsert(state["questions"], event["question"])
        _add_item(state, "question", event["question"]["id"])
    elif kind == "login":
        _upsert(state["logins"], event["login"])
        _add_item(state, "login", event["login"]["id"])
    elif kind == "queued":
        message = event["message"]
        state["queued"] = [m for m in state["queued"] if m["id"] != message["id"]] + [message]
    elif kind == "unqueue":
        state["queued"] = [m for m in state["queued"] if m["id"] != event["id"]]
    elif kind == "rewind":
        _rewind(state, event["itemId"])
    elif kind == "rate":
        if event.get("rating"):
            state["ratings"][event["turnId"]] = {
                "rating": event["rating"],
                "note": event.get("note"),
            }
        else:
            state["ratings"].pop(event["turnId"], None)
    elif kind == "access":
        state["writeAccess"] = event["write"]
    return state


def _append_text(state: dict[str, Any], event: dict[str, Any], ts: int) -> None:
    for message in state["chat"]:
        if message["id"] == event["messageId"]:
            message["text"] += event["delta"]
            break
    else:
        state["chat"].append(
            {"id": event["messageId"], "role": "assistant", "text": event["delta"], "ts": ts}
        )
    _add_item(state, "text", event["messageId"])


def _rewind(state: dict[str, Any], item_id: str) -> None:
    index = next(
        (i for i, x in enumerate(state["items"]) if x["kind"] == "user" and x["id"] == item_id),
        -1,
    )
    if index < 0:
        return

    state["items"] = state["items"][:index]
    keep = {f"{x['kind']}:{x['id']}" for x in state["items"]}
    state["chat"] = [
        m for m in state["chat"] if f"{'user' if m['role'] == 'user' else 'text'}:{m['id']}" in keep
    ]
    if not (state.get("outcomeId") and f"outcome:{state['outcomeId']}" in keep):
        state.pop("outcome", None)
        state.pop("outcomeId", None)
