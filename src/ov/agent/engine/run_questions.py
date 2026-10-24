from __future__ import annotations

import threading
from typing import Any

from ov.agent.engine.run_common import RunError, uid
from ov.agent.instances.ovproc import login as ov_login
from ov.agent.instances.ovproc import url_for
from ov.agent.tools.base import APPROVE, REJECT, Approval

LOGIN_MESSAGE_CHARS = 300
CLOSED_LOGINS = ("done", "failed", "skipped")
APPROVAL_ANSWERS = ([APPROVE], [REJECT])


class QuestionsMixin:
    def answer(self, question_id: str, answers: list[str], note: str = "") -> None:
        question = next((q for q in self.state["questions"] if q["id"] == question_id), None)
        if question is None:
            raise RunError("No such question in this run.")

        _check_answers(question, answers)

        with self._lock:
            waiter = self._questions.pop(question_id, None)
        if waiter is None:
            self._close_question(question_id)
            raise RunError("The agent is no longer waiting for this answer. Send a message to continue.")

        closed = {**question, "answers": answers}
        if note.strip():
            closed["note"] = note.strip()
        self.emit({"type": "question", "question": closed})
        waiter[1].append((answers, closed.get("note", "")))
        waiter[0].set()

    def _close_question(self, question_id: str) -> None:
        question = next((q for q in self.state["questions"] if q["id"] == question_id), None)
        if question is not None and "answers" not in question and not question.get("stopped"):
            self.emit({"type": "question", "question": {**question, "stopped": True}})

    def ask_user(self, items: list[dict[str, Any]]) -> list[str]:
        answers, _ = self._ask({"kind": "ask", "items": items})
        return answers

    def ask_approval(self, question: str, detail: str, reason: str = "") -> Approval:
        entry: dict[str, Any] = {"kind": "approval", "question": question, "detail": detail}
        if reason:
            entry["reason"] = reason
        answers, note = self._ask(entry)
        return Approval(answers == [APPROVE], note)

    def _ask(self, entry: dict[str, Any]) -> tuple[list[str], str]:
        entry = {"id": uid("q"), **entry}
        tool_id = getattr(self._local, "tool", "")
        if tool_id:
            entry["toolId"] = tool_id

        event, holder = threading.Event(), []
        with self._lock:
            self._questions[entry["id"]] = (event, holder)
            self.cancel.check()

        self.emit({"type": "question", "question": entry})
        self._wait_for(event)
        return holder[0]

    def _wait_for(self, event: threading.Event) -> None:
        with self._lock:
            self._waits += 1
            first = self._waits == 1
        if first:
            self._set_status("waiting")

        try:
            event.wait()
        finally:
            with self._lock:
                self._waits -= 1
                last = self._waits == 0

        self.cancel.check()
        if last:
            self._set_status("running")

    def require_login(self, host: str, tenant: str = "") -> bool:
        with self._lock:
            existing = next(
                (
                    item
                    for item in self.state["logins"]
                    if item["instance"] == host
                    and (item.get("tenant") or "") == tenant
                    and item["state"] not in CLOSED_LOGINS
                ),
                None,
            )

            login_id = existing["id"] if existing else uid("login")
            waiter = self._logins.setdefault(login_id, (threading.Event(), []))
            if existing is None:
                prompt = {
                    "id": login_id,
                    "instance": host,
                    "url": url_for(host),
                    "state": "needed",
                    **({"tenant": tenant} if tenant else {}),
                }
                self.emit({"type": "login", "login": prompt})

            self.cancel.check()

        self._wait_for(waiter[0])
        return waiter[1][0]

    def login(
        self,
        login_id: str,
        skip: bool,
        token: str = "",
        screen: tuple[int, int] | None = None,
        remember: bool = False,
    ) -> dict[str, Any]:
        prompt = next((item for item in self.state["logins"] if item["id"] == login_id), None)
        if prompt is None:
            raise RunError("No such login prompt.")
        if skip:
            self.emit({"type": "login", "login": {**prompt, "state": "skipped"}})
            self._resolve_login(login_id, False)
            return {"ok": False, "message": "Skipped"}

        self.emit({"type": "login", "login": {**prompt, "state": "running"}})

        result = ov_login(prompt["url"], prompt.get("tenant") or "", token, screen, remember)
        ok = result.code == 0
        message = "" if ok else result.message[-LOGIN_MESSAGE_CHARS:] or "Sign-in failed."
        update = {**prompt, "state": "done" if ok else "failed"}
        if not ok:
            update["message"] = message

        self.emit({"type": "login", "login": update})
        if ok:
            self._resolve_login(login_id, True)
        return {"ok": ok, "message": message}

    def _resolve_login(self, login_id: str, ok: bool) -> None:
        with self._lock:
            waiter = self._logins.pop(login_id, None)
        if waiter is not None:
            waiter[1].append(ok)
            waiter[0].set()


def _check_answers(question: dict[str, Any], answers: list[str]) -> None:
    if question["kind"] == "approval":
        if answers not in APPROVAL_ANSWERS:
            raise RunError(f"Answer an approval with {APPROVE} or {REJECT}.")
        return
    if len(answers) != len(question["items"]) or not all(a.strip() for a in answers):
        raise RunError(f"Answer all {len(question['items'])} questions.")
