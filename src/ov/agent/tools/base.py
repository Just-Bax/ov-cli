from __future__ import annotations

import itertools
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ov.agent.engine.cancel import Cancel
from ov.agent.engine.guard import Effect, Verdict

if TYPE_CHECKING:
    from ov.agent.engine.browsing import BrowserSlot

MAX_OUTPUT = 12_000
SECRET_MASK = "***"
LABEL_CHARS = 200
LABEL_CUT = "..."
APPROVE = "Approve"
UI_ONLY = (
    "Not done: the browser is open, so changes happen in the UI the way a user makes them. Do this step in the "
    "browser with the browser_ tools; ov, SQL and commands only read while it is open. If the UI cannot do it, "
    "stop and tell the user."
)
REJECT = "Reject"
REJECTED_WITH_NOTE = "The user rejected this and said: {note}"

SECRET_JSON = re.compile(
    r'("[\w.\-]*(?:pass(?:word|wd)?|secret|token|api_?key|private_?key|credential)[\w.\-]*"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)
_SECRET_ASSIGN = re.compile(
    r"""(\b[\w.\-]*(?:password|passwd|secret|api_?key|private_?key|credential|access_?token|auth_?token)[\w.\-]*"""
    r"""\s*[=:]\s*)(["']?)([^\s"',;]{4,})\2""",
    re.IGNORECASE,
)


def brief(text: object) -> str:
    flat = re.sub(r"\s+", " ", str(text)).strip()
    if len(flat) <= LABEL_CHARS:
        return flat
    return flat[: LABEL_CHARS - len(LABEL_CUT)] + LABEL_CUT


BACKGROUND_PARAM = {
    "type": "boolean",
    "description": "Run in the background for calls that may take over a minute; the result arrives later "
    "as a message while you continue or end your turn",
}

_serials = itertools.count(1)


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Approval:
    approved: bool
    note: str


class ToolContext(Protocol):
    id: str
    work_dir: Path
    cancel: Cancel
    vision: bool
    instance: str
    opened: set[str]
    browser: BrowserSlot

    def emit(self, event: dict[str, Any]) -> None: ...
    def has_outcome(self) -> bool: ...
    def ask_user(self, items: list[dict[str, Any]]) -> list[str]: ...
    def ask_approval(self, question: str, detail: str, reason: str = "") -> Approval: ...
    def require_login(self, host: str, tenant: str = "", web: bool = False) -> bool: ...
    def attach_image(self, name: str, url: str) -> None: ...
    def record_edit(self, path: str, before: str, after: str, created: bool) -> None: ...
    def finish(self, outcome: dict[str, Any]) -> None: ...
    def can_write(self) -> bool: ...
    def auto_approves(self) -> bool: ...
    def full_access(self) -> bool: ...
    def load_case(self, ref: str) -> str: ...
    def read_thread(self, thread_id: str) -> str: ...
    def judge_command(self, command: str, folder: str, scripts: dict[str, str]) -> Verdict: ...
    def judge_page_action(self, action: str) -> Verdict: ...
    def judge_risk(self, change: str) -> Verdict: ...
    def drive_browser(self, goal: str, cancel: Cancel) -> str: ...


Handler = Callable[[dict[str, Any], ToolContext], str]


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    label: Callable[[dict[str, Any]], str]
    handler: Handler
    silent: bool = False

    @property
    def spec(self) -> dict[str, Any]:
        properties = self.properties if self.silent else {**self.properties, "background": BACKGROUND_PARAM}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": self.required,
                    "additionalProperties": False,
                },
            },
        }


def string_param(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def int_param(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


def strings_param(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def serial() -> int:
    return next(_serials)


def mask_secrets(text: str) -> str:
    masked = SECRET_JSON.sub(rf'\1"{SECRET_MASK}"', text)
    return _SECRET_ASSIGN.sub(rf"\1\2{SECRET_MASK}\2", masked)


def clip(text: str, ctx: ToolContext, what: str) -> str:
    text = mask_secrets(text)
    if len(text) <= MAX_OUTPUT:
        return text

    name = f"output-{int(time.time() * 1000)}-{serial()}.txt"
    (ctx.work_dir / name).write_text(text, encoding="utf-8")
    return (
        f"{text[:MAX_OUTPUT]}\n\n[truncated: {len(text)} chars total. Full {what} saved as "
        f'"{name}"; read more with run_read]'
    )


def approved(ctx: ToolContext, question: str, detail: str) -> bool:
    if ctx.full_access():
        return True

    reason = ""
    if ctx.auto_approves():
        verdict = ctx.judge_risk(f"{question}\n{detail}")
        if verdict.effect == Effect.ROUTINE:
            return True
        reason = verdict.reason

    approval = ctx.ask_approval(question, detail, reason)
    if not approval.approved and approval.note:
        raise ToolError(REJECTED_WITH_NOTE.format(note=approval.note))
    return approval.approved


def raising_tool_errors(handler: Handler, *errors: type[Exception]) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return handler(args, ctx)
        except errors as exc:
            raise ToolError(str(exc)) from None

    return wrapped
