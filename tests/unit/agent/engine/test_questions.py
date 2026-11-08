from __future__ import annotations

import json
import threading
import time

import pytest
from helpers.agent import wait_for

from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db
from ov.agent.storage.models import Access


def _item(question: str) -> dict:
    return {"header": "", "question": question, "options": [{"label": "a"}, {"label": "b"}], "multiple": False}


def test_stopping_closes_open_questions(logged_in, monkeypatch):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import runs

    item = {"header": "Instance", "question": "Which instance?", "options": [{"label": "acme"}, {"label": "other"}]}
    ask = {"questions": [item]}
    replies = iter(
        [
            StreamResult(
                tool_calls=[
                    {"id": "c1", "type": "function", "function": {"name": "run_ask", "arguments": json.dumps(ask)}}
                ]
            ),
            StreamResult(text="Stopped."),
        ]
    )
    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", lambda *a, cancel, on_text, **_: next(replies))
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    run = runs.create({"access": "read", "prompt": "help", "instance": "acme"}, "copilot", "test-model")
    wait_for(lambda: run.state["questions"])

    question = run.state["questions"][0]
    run.stop()
    wait_for(lambda: run.state["questions"][0].get("stopped"))

    assert run.state["questions"][0]["stopped"] and "answers" not in run.state["questions"][0]
    with pytest.raises(RunError, match="no longer waiting"):
        run.answer(question["id"], ["acme"])


def test_two_open_questions_keep_the_run_waiting(logged_in):
    from ov.agent.engine.run_manager import runs

    db.create_thread("rwait", "t", "copilot", "m", instance=None, access=Access.READ)
    run = runs.get("rwait")
    answers: list[str] = []
    threads = [threading.Thread(target=lambda q=q: answers.extend(run.ask_user([_item(q)]))) for q in ("one", "two")]
    for t in threads:
        t.start()
    wait_for(lambda: len(run.state["questions"]) == 2)

    assert run.state["summary"]["status"] == "waiting"
    run.answer(run.state["questions"][0]["id"], ["a"])
    time.sleep(0.2)
    assert run.state["summary"]["status"] == "waiting"
    run.answer(run.state["questions"][1]["id"], ["b"])
    for t in threads:
        t.join(2)
    assert sorted(answers) == ["a", "b"] and run.state["summary"]["status"] == "running"


def test_a_skipped_sign_in_is_marked_skipped_not_failed(logged_in, monkeypatch):
    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": "x"}, "copilot", "m")
    prompt = {"id": "login_1", "instance": "acme.example", "url": "https://acme.example", "state": "needed"}
    run.emit({"type": "login", "login": prompt})
    assert run.login("login_1", skip=True) == {"ok": False, "message": "Skipped"}
    assert run.state["logins"][0]["state"] == "skipped"


def _asking(run, ask):
    holder: list = []
    thread = threading.Thread(target=lambda: holder.append(ask()))
    thread.start()
    wait_for(lambda: run.state["questions"])
    return thread, holder


def test_a_batch_is_answered_all_at_once(logged_in):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import runs

    db.create_thread("rbatch", "t", "copilot", "m", instance=None, access=Access.READ)
    run = runs.get("rbatch")
    thread, holder = _asking(run, lambda: run.ask_user([_item("one"), _item("two")]))
    question = run.state["questions"][0]
    assert question["kind"] == "ask" and len(question["items"]) == 2
    with pytest.raises(RunError, match="all 2"):
        run.answer(question["id"], ["a"])

    run.answer(question["id"], ["a", "my own"])
    thread.join(2)
    assert holder == [["a", "my own"]] and run.state["questions"][0]["answers"] == ["a", "my own"]


def test_an_approval_keeps_the_rejection_note(logged_in):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import runs

    db.create_thread("rappr", "t", "copilot", "m", instance=None, access=Access.ASK)
    run = runs.get("rappr")
    thread, holder = _asking(run, lambda: run.ask_approval("Run it?", "rm -rf build", "deletes files"))
    question = run.state["questions"][0]
    assert (question["kind"], question["detail"], question["reason"]) == ("approval", "rm -rf build", "deletes files")
    with pytest.raises(RunError, match="Approve or Reject"):
        run.answer(question["id"], ["Maybe"])

    run.answer(question["id"], ["Reject"], " keep build ")
    thread.join(2)
    assert holder[0].approved is False and holder[0].note == "keep build"
    assert run.state["questions"][0]["note"] == "keep build"


def _remembered(base_url: str, expires_at: float) -> None:
    from ov.onevizion import session as session_store
    from ov.onevizion.session import Session

    session_store.save(
        Session(base_url=base_url, mode="remembered", bearer_token="A:B", expires_at=expires_at, cookies={"J": "x"})
    )


def _web_sign_in(run, monkeypatch):
    from ov.agent.instances.ovproc import OvResult

    calls: list = []
    monkeypatch.setattr(
        "ov.agent.engine.run_questions.ov_login",
        lambda url, tenant, token, screen, remember, web_only: (
            calls.append((remember, web_only)) or OvResult(0, "", "")
        ),
    )
    holder: list = []
    thread = threading.Thread(target=lambda: holder.append(run.require_login("acme.onevizion.test", "", web=True)))
    thread.start()
    wait_for(lambda: run.state["logins"])

    prompt = run.state["logins"][0]
    run.login(prompt["id"], skip=False)
    thread.join(2)
    return prompt, calls, holder


@pytest.mark.parametrize(
    ("expires_at", "keep", "remember"),
    [(4102444800.0, True, False), (1.0, False, True)],
)
def test_a_web_sign_in_keeps_a_working_token_or_renews_it_as_before(logged_in, monkeypatch, expires_at, keep, remember):
    from helpers.sessions import BASE_URL

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    from ov.agent.engine.run_manager import runs

    _remembered(BASE_URL, expires_at)
    run = runs.create({"access": "auto", "prompt": "x"}, "copilot", "m")

    prompt, calls, holder = _web_sign_in(run, monkeypatch)
    assert prompt["need"] == "web" and prompt["keepToken"] is keep
    assert calls == [(remember, keep)] and holder == [True]


def test_a_web_sign_in_takes_no_api_token(logged_in, monkeypatch):
    from ov.agent.engine.run_common import RunError

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": "x"}, "copilot", "m")
    prompt = {"id": "login_1", "instance": "acme.example", "url": "https://acme.example", "state": "needed"}
    run.emit({"type": "login", "login": {**prompt, "need": "web", "keepToken": True}})
    with pytest.raises(RunError, match="needs the browser"):
        run.login("login_1", skip=False, token="A:B")
