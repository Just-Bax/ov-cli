from __future__ import annotations

import json
import threading
import time

import pytest

from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db


def test_stopping_closes_open_questions(logged_in, monkeypatch):
    from ov.agent.engine.run import STOPPED_ANSWER, RunError, runs

    ask = {"question": "Which instance?", "options": ["acme", "other"]}
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

    run = runs.create({"prompt": "help", "instance": "acme"}, "test-model")
    for _ in range(100):
        if run.state["questions"]:
            break
        time.sleep(0.05)

    question = run.state["questions"][0]
    run.stop()
    for _ in range(100):
        if run.state["questions"][0].get("answer"):
            break
        time.sleep(0.05)

    assert run.state["questions"][0]["answer"] == STOPPED_ANSWER
    with pytest.raises(RunError, match="no longer waiting"):
        run.answer(question["id"], "acme")


def test_two_open_questions_keep_the_run_waiting(logged_in):
    from ov.agent.engine.run import runs

    db.create_thread("rwait", "t", "m", prompt="x", instance=None, allow_write=False)
    run = runs.get("rwait")
    answers: list[str] = []
    threads = [
        threading.Thread(target=lambda q=q: answers.append(run.ask_user(q, ["a", "b"], False))) for q in ("one", "two")
    ]
    for t in threads:
        t.start()
    for _ in range(100):
        if len(run.state["questions"]) == 2:
            break
        time.sleep(0.02)
    assert run.state["summary"]["status"] == "waiting"
    run.answer(run.state["questions"][0]["id"], "a")
    time.sleep(0.2)
    assert run.state["summary"]["status"] == "waiting"
    run.answer(run.state["questions"][1]["id"], "b")
    for t in threads:
        t.join(2)
    assert sorted(answers) == ["a", "b"] and run.state["summary"]["status"] == "running"
