from __future__ import annotations

import re

from ov.agent.engine.run_common import RunError
from ov.agent.storage.models import UsageKind

TITLE_CHARS = 72
NAMING_INPUT_CHARS = 2000
NAMING_MAX_TOKENS = 200
NAMING_PROMPT = (
    "You write titles for a list of conversations. You never answer or act on the request. "
    "Given the user's first message between <message> tags, reply with a 3 to 7 word title "
    "naming its topic, like a ticket title. Reply with the title only: one line, no quotes, no "
    "markdown, no trailing period."
)
MAX_TITLE_WORDS = 8
RETITLE_CHARS = 1500
_TITLE_PREFIX = re.compile(r"^(title|subject|topic)\s*[:\-]\s*", re.IGNORECASE)
_TITLE_NOISE = "\"'#*`_.:;,- "


class TitlesMixin:
    def _name_later(self, text: str) -> None:
        self._spawn(self._name, self.state["summary"]["title"], text)

    def _name(self, placeholder: str, text: str) -> None:
        title = self._ask_title(f"<message>\n{text[:NAMING_INPUT_CHARS]}\n</message>")
        if self.state["summary"]["title"] == placeholder:
            self.rename(title)

    def _ask_title(self, body: str) -> str:
        model = self._helper_model()
        reply, usage = self.agent.complete(model, NAMING_PROMPT, body, NAMING_MAX_TOKENS)
        self.record_usage(model, UsageKind.NAMING, usage)
        title = clean_title(reply)
        if not title:
            raise RunError(f"{model} did not suggest a title.")
        return title

    def retitle(self) -> str:
        with self._lock:
            chat = list(self.state["chat"])

        asked = next((m["text"] for m in chat if m["role"] == "user"), "")
        replied = next((m["text"] for m in reversed(chat) if m["role"] == "assistant" and m["text"].strip()), "")
        body = f"<message>\n{asked[:NAMING_INPUT_CHARS]}\n</message>\n\n<answer>\n{replied[:RETITLE_CHARS]}\n</answer>"
        title = self._ask_title(body)
        self.rename(title)
        return title

    def rename(self, title: str) -> None:
        cleaned = short_title(title, TITLE_CHARS)
        if not cleaned:
            raise RunError("A run needs a name.")
        self.emit({"type": "meta", "title": cleaned})


def short_title(text: str, limit: int) -> str:
    words = " ".join(text.split())
    if len(words) <= limit:
        return words
    head = words[:limit]
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip(_TITLE_NOISE)


def clean_title(reply: str) -> str:
    line = next((x for x in reply.splitlines() if x.strip()), "")
    title = _TITLE_PREFIX.sub("", line.strip().strip(_TITLE_NOISE)).strip(_TITLE_NOISE)
    return short_title(" ".join(title.split()[:MAX_TITLE_WORDS]), TITLE_CHARS)
