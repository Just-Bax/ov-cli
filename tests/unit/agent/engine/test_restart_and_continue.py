from __future__ import annotations

import copy

from helpers.agent import wait_done, wait_for

from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db


def _copilot_chat(monkeypatch, *texts: str) -> list[list[dict]]:
    sent: list[list[dict]] = []
    replies = iter(texts)

    def stream(model, messages, *a, cancel, on_text, **_):
        sent.append(copy.deepcopy(messages))
        text = next(replies)
        on_text(text)
        return StreamResult(text=text)

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", stream)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    return sent


def _start(prompt: str = "which tags?"):
    from ov.agent.engine.run_manager import runs

    return runs.create({"access": "read", "prompt": prompt, "instance": "acme"}, "copilot", "test-model")


def test_a_thread_cut_off_by_a_restart_carries_on_by_itself(logged_in, monkeypatch):
    from ov.agent.engine.run import RESTART_NOTE
    from ov.agent.engine.run_manager import runs

    sent = _copilot_chat(monkeypatch, "Looking.", "Carried on.")
    run = _start()
    wait_done(run)
    db.update_thread(run.id, status="running")

    runs.close()
    db.close()
    runs.resume_interrupted()

    resumed = runs.get(run.id)
    wait_for(lambda: len(sent) == 2)
    wait_done(resumed)
    assert RESTART_NOTE in sent[1][-1]["content"]
    assert resumed.state["chat"][-1]["text"] == "Carried on."
    statuses = [
        e["event"].get("error") or e["event"]["status"]
        for e in db.load_events(run.id)
        if e["event"]["type"] == "status"
    ]
    assert statuses[-3:] == ["Interrupted by a restart.", "running", "done"]


def test_a_finished_thread_is_not_resumed(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    sent = _copilot_chat(monkeypatch, "Done.")
    run = _start()
    wait_done(run)

    runs.close()
    db.close()
    runs.resume_interrupted()

    assert len(sent) == 1 and runs.get(run.id).state["summary"]["status"] == "done"
