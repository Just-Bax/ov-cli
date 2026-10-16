from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from ov.agent.storage import db

MS_PER_SECOND = 1000
VERDICTS = {
    "fix": "Needs a fix",
    "fixed": "Fixed",
    "user_action": "Needs user action",
    "expected": "Works as expected",
    "info": "Info",
    "unknown": "Unclear",
}


def _when(ms: int) -> str:
    return datetime.fromtimestamp(ms / MS_PER_SECOND).strftime("%Y-%m-%d %H:%M")


def _cost(cost: dict[str, Any]) -> str:
    if not cost["requests"]:
        return "not tracked"
    if cost["usd"]:
        return f"about ${cost['usd']:,.2f} of Claude plan usage"
    return f"{cost['credits']:,.2f} credits"


def _header(state: dict[str, Any]) -> list[str]:
    summary = state["summary"]
    facts = [f"Model: {summary['model']} ({summary['provider']})"]
    if summary.get("instance"):
        facts.append(f"Instance: {summary['instance']}")
    facts.append(f"Started: {_when(summary['createdAt'])}")
    facts.append(f"Updated: {_when(summary['updatedAt'])}")
    facts.append(f"Status: {summary['status']}")
    cost = db.thread_cost(summary["id"])
    facts.append(f"Cost: {_cost(cost)}")
    return [f"# {summary['title']}", "", " | ".join(facts)]


def _tool(tool: dict[str, Any]) -> str:
    timing = f", {tool['ms'] / MS_PER_SECOND:.1f} s" if tool.get("ms") is not None else ""
    return f"- {tool['label']} ({tool['status']}{timing})"


def _change(change: dict[str, Any]) -> list[str]:
    lines = [f"#### Proposed change: {change['title']}", ""]
    for label, key in (("What", "what"), ("Why", "why"), ("How", "how")):
        if change.get(key):
            lines += [f"**{label}:** {change[key]}", ""]
    fence = "````" if "```" in change["after"] else "```"
    return [*lines, f"{fence}{change['language']}", change["after"].rstrip("\n"), fence]


def _outcome(outcome: dict[str, Any]) -> list[str]:
    lines = ["#### Findings", ""]
    for issue in outcome.get("issues") or []:
        lines.append(f"- **{issue['title']}** ({VERDICTS.get(issue['verdict'], issue['verdict'])}): {issue['summary']}")
    if outcome.get("reply"):
        lines += ["", "**Suggested reply:**", "", outcome["reply"]]
    return lines


def _question(question: dict[str, Any]) -> list[str]:
    answers = question.get("answers") or []
    if question["kind"] == "approval":
        lines = [f"**Approval:** {question['question']}"]
        if answers:
            lines.append(f"**Answer:** {answers[0]}")
        if question.get("note"):
            lines.append(f"**Note:** {question['note']}")
        return lines

    lines = []
    for index, item in enumerate(question["items"]):
        lines.append(f"**Question:** {item['question']}")
        if index < len(answers):
            lines.append(f"**Answer:** {answers[index]}")
    return lines


def _text(message: dict[str, Any]) -> list[str]:
    text = message["text"].strip()
    return [text] if text else []


def _login(login: dict[str, Any]) -> list[str]:
    return [f"- Sign-in to {login['instance']}: {login['state']}"]


RENDERERS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "text": _text,
    "tool": lambda tool: [_tool(tool)],
    "change": _change,
    "question": _question,
    "login": _login,
}


def _agent_part(state: dict[str, Any], kind: str, entry: dict[str, Any] | None) -> list[str]:
    if kind == "outcome":
        return _outcome(state["outcome"]) if state.get("outcome") else []
    render = RENDERERS.get(kind)
    return render(entry) if render is not None and entry is not None else []


def _user(message: dict[str, Any]) -> list[str]:
    lines = [f"## You, {_when(message['ts'])}", "", message["text"].strip()]
    names = [f["name"] for f in message.get("files") or []]
    return [*lines, "", f"Attached: {', '.join(names)}"] if names else lines


def to_markdown(state: dict[str, Any]) -> str:
    chat = {m["id"]: m for m in state["chat"]}
    found = {
        "text": chat,
        "tool": {t["id"]: t for t in state["tools"]},
        "change": {c["id"]: c for c in state["changes"]},
        "question": {q["id"]: q for q in state["questions"]},
        "login": {x["id"]: x for x in state["logins"]},
    }

    lines = _header(state)
    previous = ""
    for item in state["items"]:
        kind, item_id = item["kind"], item["id"]
        if kind == "user":
            if item_id in chat:
                lines += ["", *_user(chat[item_id])]
            previous = "user"
            continue

        part = _agent_part(state, kind, found.get(kind, {}).get(item_id))
        if not part:
            continue
        if previous in ("", "user"):
            lines += ["", "## Agent"]
        if not (kind == "tool" and previous == "tool"):
            lines.append("")
        lines += part
        previous = kind

    return "\n".join(lines).strip() + "\n"
