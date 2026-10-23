from __future__ import annotations

from typing import Any

INTERRUPTED_RESULT = (
    "Error: interrupted before it finished, so its result is unknown. Check the current state before running it again."
)


def answered(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixed: list[dict[str, Any]] = []
    pending: list[str] = []
    for message in messages:
        if message["role"] == "tool":
            if message["tool_call_id"] in pending:
                pending.remove(message["tool_call_id"])
            fixed.append(message)
            continue
        fixed += [_interrupted(call_id) for call_id in pending]
        pending = [c["id"] for c in message.get("tool_calls") or []]
        fixed.append(message)

    return fixed + [_interrupted(call_id) for call_id in pending]


def _interrupted(call_id: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": INTERRUPTED_RESULT}
