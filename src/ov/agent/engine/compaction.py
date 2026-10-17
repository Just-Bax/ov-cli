from __future__ import annotations

import json
from typing import Any

COMPACT_SHARE = 0.85
KEEP_RECENT_SHARE = 0.2
CHARS_PER_TOKEN = 4
IMAGE_TOKENS = 1500
SUMMARY_MAX_TOKENS = 8000
TRANSCRIPT_TOOL_CHARS = 4000
TRANSCRIPT_ARGS_CHARS = 2000
SUMMARY_HEADER = (
    "[The earlier part of this conversation was compacted to save context. This is its summary; "
    "the messages after it continue from where it ends.]\n\n"
)
SUMMARY_PROMPT = """You compact the history of an agent's working session so the agent can carry on with a
fresh context. The agent troubleshoots OneVizion instances for the user with tools (SQL, API calls,
Datadog, PagerDuty, a browser, workspace files). You get the older part of the conversation between
<conversation> tags. You never continue the work or answer the user; you only write the summary.

Write a dense summary in plain Markdown with these sections, leaving out any that are empty:

1. Request: what the user asked for, in their own words where it matters, and every later
   instruction, correction or preference they gave.
2. Context: instance, case, environment, objects and their exact ids, names, paths and URLs.
3. Findings: what the agent learned, with the concrete evidence (queries, values, errors, log
   lines) needed to trust it without running the tools again.
4. Done: changes already made (to instances, files, services), and approvals or answers the user
   gave.
5. Open: unanswered questions, failed attempts and why they failed, and what is still to do.
6. Now: what the agent was doing when the history was cut, and the next step.

Keep identifiers, numbers, SQL and file paths exact. Do not invent anything. Reply with the summary
only."""


def compact_at(window: int | None, limit: int) -> int:
    return int(min(window or limit, limit) * COMPACT_SHARE)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(_message_tokens(m) for m in messages)


def _message_tokens(message: dict[str, Any]) -> int:
    content = message.get("content")
    images = 0
    if isinstance(content, list):
        images = sum(1 for part in content if part.get("type") == "image_url")
        content = [part for part in content if part.get("type") != "image_url"]
    text = json.dumps({**message, "content": content})
    return len(text) // CHARS_PER_TOKEN + images * IMAGE_TOKENS


def cut_point(messages: list[dict[str, Any]], keep_tokens: int) -> int | None:
    boundaries = [i for i in range(2, len(messages)) if messages[i]["role"] in ("user", "assistant")]
    if not boundaries:
        return None

    tail = 0
    chosen = None
    for index in range(len(messages) - 1, 1, -1):
        tail += _message_tokens(messages[index])
        if tail > keep_tokens:
            break
        if index in boundaries:
            chosen = index
    return chosen or boundaries[-1]


def transcript(messages: list[dict[str, Any]]) -> str:
    lines = [_line(m) for m in messages]
    return "<conversation>\n" + "\n\n".join(line for line in lines if line) + "\n</conversation>"


def _line(message: dict[str, Any]) -> str:
    role = message["role"]
    if role == "tool":
        return f"Tool result:\n{_text(message.get('content'))[:TRANSCRIPT_TOOL_CHARS]}"

    said = _text(message.get("content"))
    if role == "user":
        return f"User:\n{said}"

    calls = [
        f"Agent called {c['function']['name']}({c['function']['arguments'][:TRANSCRIPT_ARGS_CHARS]})"
        for c in message.get("tool_calls") or []
    ]
    return "\n".join([*([f"Agent:\n{said}"] if said else []), *calls])


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(part["text"] if part["type"] == "text" else "[image]" for part in content)


def rebuilt(messages: list[dict[str, Any]], cut: int, summary: str) -> list[dict[str, Any]]:
    return [messages[0], {"role": "user", "content": SUMMARY_HEADER + summary}, *messages[cut:]]
