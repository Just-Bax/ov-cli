from __future__ import annotations

import queue
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from playwright.sync_api import Dialog as PageDialog

from ov.browser.model import BrowserError, Dialog

PROMPT = "prompt"
NO_DIALOG = "No dialog is open on the page."

Notify = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class _Answer:
    accept: bool
    text: str


class Dialogs:
    def __init__(self, notify: Notify) -> None:
        self.open: Dialog | None = None
        self._notify = notify
        self._answers: queue.SimpleQueue[_Answer] = queue.SimpleQueue()

    def hold(self, dialog: PageDialog) -> None:
        self.open = Dialog(dialog.type, dialog.message, dialog.default_value)
        self._notify({"dialog": asdict(self.open)})

        answer = self._answers.get()
        if not answer.accept:
            dialog.dismiss()
        elif dialog.type == PROMPT:
            dialog.accept(answer.text)
        else:
            dialog.accept()

    def answer(self, accept: bool, text: str) -> None:
        if self.open is None:
            raise BrowserError(NO_DIALOG)
        self.open = None
        self._notify({"dialog": None})
        self._answers.put(_Answer(accept, text))
