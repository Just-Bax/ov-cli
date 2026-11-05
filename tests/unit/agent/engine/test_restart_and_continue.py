from __future__ import annotations

import copy

import pytest
from helpers.agent import TEST_TITLE_REPLY, is_title_prompt, wait_done, wait_for

from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db

SUMMARY = "The user asked which tags exist. The agent found A and B."


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


def test_a_thread_continues_in_a_new_one_from_a_summary(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    summarized: list[tuple[str, str]] = []

    def complete(model, system, text, *a):
        if is_title_prompt(system):
            return TEST_TITLE_REPLY, None
        summarized.append((model, text))
        return SUMMARY, None

    _copilot_chat(monkeypatch, "The tags are A and B.")
    monkeypatch.setattr("ov.agent.integrations.copilot.complete", complete)
    run = _start()
    wait_done(run)

    continued = runs.continue_in_new(run.id)
    wait_done(continued)

    source_title = run.state["summary"]["title"]
    assert continued.state["parent"] == {"id": run.id, "title": source_title}
    assert (continued.state["summary"]["parentId"], continued.state["summary"]["origin"]) == (run.id, "summary")
    assert [t["id"] for t in db.child_threads(run.id)] == [continued.id]
    assert continued.state["summary"]["title"] == f"{source_title} (continued)"
    assert (continued.provider, continued.model, continued.instance) == ("copilot", "test-model", "acme")
    assert continued.state["chat"][-1]["text"].startswith(f"Continued from **{source_title}**")
    assert continued.messages[1]["content"].endswith(SUMMARY) and len(continued.messages) == 2
    model, transcript = summarized[-1]
    assert model == "test-model" and "User:\nwhich tags?" in transcript and "The tags are A and B." in transcript
    assert db.thread_cost(continued.id)["requests"] == 0


def test_a_busy_or_empty_thread_cannot_be_continued(logged_in, monkeypatch):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import runs

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    run = _start()
    with pytest.raises(RunError, match="nothing to carry over"):
        runs.continue_in_new(run.id)

    run._busy = True
    with pytest.raises(RunError, match="before continuing in a new thread"):
        runs.continue_in_new(run.id)
    run._busy = False
