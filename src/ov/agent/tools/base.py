from __future__ import annotations

import itertools
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ov.agent.engine.cancel import Cancel

MAX_OUTPUT = 24_000
SECRET_MASK = "***"
LABEL_CHARS = 60
APPROVE = "Approve"
REJECT = "Reject"

SECRET_JSON = re.compile(
    r'("[\w.\-]*(?:pass(?:word|wd)?|secret|token|api_?key|private_?key|credential)[\w.\-]*"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)
_SECRET_ASSIGN = re.compile(
    r"""(\b[\w.\-]*(?:password|passwd|secret|api_?key|private_?key|credential|access_?token|auth_?token)[\w.\-]*"""
    r"""\s*[=:]\s*)(["']?)([^\s"',;]{4,})\2""",
    re.IGNORECASE,
)

_serials = itertools.count(1)


class ToolError(Exception):
    pass


class ToolContext(Protocol):
    work_dir: Path
    cancel: Cancel
    vision: bool
    instance: str
    opened: set[str]

    def emit(self, event: dict[str, Any]) -> None: ...
    def has_outcome(self) -> bool: ...
    def ask_user(self, question: str, options: list[str], multiple: bool, detail: str | None = None) -> str: ...
    def require_login(self, host: str, tenant: str = "") -> bool: ...
    def attach_image(self, name: str, url: str) -> None: ...
    def record_edit(self, path: str, before: str, after: str, created: bool) -> None: ...
    def finish(self, outcome: dict[str, Any]) -> None: ...
    def can_write(self) -> bool: ...
    def load_case(self, ref: str) -> str: ...


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
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
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
    return ctx.ask_user(question, [APPROVE, REJECT], False, detail) == APPROVE


def raising_tool_errors(handler: Handler, *errors: type[Exception]) -> Handler:
    def wrapped(args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return handler(args, ctx)
        except errors as exc:
            raise ToolError(str(exc)) from None

    return wrapped
