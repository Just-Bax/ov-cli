from __future__ import annotations

import threading

import pytest
from helpers.agent import SLOW_POLLS, wait_done, wait_for

from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db
from ov.agent.storage.models import Access, Provider

BREAK = "\n\n"


def test_a_tool_call_left_without_a_result_is_answered_before_the_next_request(logged_in, monkeypatch):
    sent: list[list[dict]] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        sent.append([dict(m) for m in messages])
        return StreamResult(text="Carrying on.")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)

    call = {"id": "c9", "type": "function", "function": {"name": "ov_sql", "arguments": "{}"}}
    run._messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
    run.emit({"type": "tool", "tool": {"id": "c9", "name": "ov_sql", "label": "SQL", "status": "running"}})
    run._fail(RuntimeError("tool thread died"))

    assert run.state["tools"][-1]["status"] == "error"

    run.follow_up("continue", [], steer=False)
    wait_for(lambda: len(sent) == 2)

    last = sent[-1]
    at = next(i for i, m in enumerate(last) if m.get("tool_calls") == [call])
    assert last[at + 1] == {"role": "tool", "tool_call_id": "c9", "content": "Error: interrupted."}
    assert last[at + 2]["role"] == "user"


def test_the_system_prompt_follows_the_access_mode(logged_in, monkeypatch):
    sent: list[str] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        sent.append(messages[0]["content"])
        return StreamResult(text="ok")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)
    run.set_access(Access.AUTO)
    run.follow_up("go", [], steer=False)
    wait_for(lambda: len(sent) == 2)

    assert "currently OFF: read-only" in sent[0]
    assert "changes run without asking the user" in sent[1]


def test_a_queued_message_waits_for_the_turn_and_a_steered_one_does_not(logged_in, monkeypatch):
    gate = threading.Event()
    seen: list[list[str]] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        seen.append([m["content"] for m in messages if m["role"] == "user"])
        if len(seen) == 1:
            gate.wait(5)
            return StreamResult(
                text="Working.",
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "ov", "arguments": '{"args": []}'}}],
            )
        return StreamResult(text="ok")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(0, "ok\n", ""))

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "start", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_for(lambda: seen)
    run.follow_up("later", [], steer=False)
    run.follow_up("now", [], steer=True)
    gate.set()
    wait_for(lambda: len(seen) >= 3 and run.state["summary"]["status"] == "done", polls=SLOW_POLLS)

    assert seen[1][-1].endswith(BREAK + "now") and not any(m.endswith("later") for m in seen[1])
    assert seen[2][-1].startswith("[Sent ") and seen[2][-1].endswith(BREAK + "later")
    assert not run.state["queued"]


def test_queued_messages_are_sent_one_turn_at_a_time(logged_in, monkeypatch):
    gate = threading.Event()
    seen: list[str] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        seen.append(messages[-1]["content"])
        if len(seen) == 1:
            gate.wait(5)
        return StreamResult(text="ok")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "start", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_for(lambda: seen)
    run.follow_up("one", [], steer=False)
    run.follow_up("two", [], steer=False)
    gate.set()
    wait_for(lambda: len(seen) >= 3 and run.state["summary"]["status"] == "done", polls=SLOW_POLLS)

    assert [m.rsplit(BREAK, 1)[-1] for m in seen[1:]] == ["one", "two"]
    assert not run.state["queued"]


def test_a_steer_reaches_claude_with_the_next_tool_result(logged_in, monkeypatch):
    from ov.agent.engine.run import runs
    from ov.agent.storage import db

    db.create_thread("rsteer", "t", Provider.CLAUDE, "m", prompt="x", instance=None, access=Access.READ)
    run = runs.get("rsteer")
    run._busy = True
    monkeypatch.setattr(run, "call_tool_named", lambda name, args: ("rows", []))
    run.follow_up("skip VHMKFBC_PKG", [], steer=False)
    run.follow_up("after the turn", [], steer=False)
    run.steer_queued(run.state["queued"][0]["id"])

    output, _ = run.call_tool_with_steering("ov_sql", {})
    again, _ = run.call_tool_with_steering("ov_sql", {})
    run._busy = False

    assert output.startswith("rows") and output.endswith("[The user wrote while you worked: skip VHMKFBC_PKG]")
    assert again == "rows"
    assert [m["text"] for m in run.state["queued"]] == ["after the turn"]
    assert run.state["chat"][-1]["text"] == "skip VHMKFBC_PKG"


def test_an_edited_queued_message_keeps_its_place(logged_in):
    from ov.agent.engine.run import RunError, runs

    db.create_thread("redit", "t", Provider.CLAUDE, "m", prompt="x", instance=None, access=Access.READ)
    run = runs.get("redit")
    run._busy = True
    run.follow_up("first", [], steer=False)
    run.follow_up("second", [], steer=False)
    first = run.state["queued"][0]["id"]

    run.edit_queued(first, "first, edited")
    with pytest.raises(RunError, match="needs text or files"):
        run.edit_queued(first, "  ")
    run._busy = False

    assert [m["text"] for m in run.state["queued"]] == ["first, edited", "second"]
    assert run._queue[0][0]["text"] == "first, edited"


def test_queued_messages_can_be_reordered(logged_in):
    from ov.agent.engine.run import RunError, runs

    db.create_thread("rmove", "t", Provider.CLAUDE, "m", prompt="x", instance=None, access=Access.READ)
    run = runs.get("rmove")
    run._busy = True
    for text in ("a", "b", "c"):
        run.follow_up(text, [], steer=False)
    a, b, c = (m["id"] for m in run.state["queued"])

    run.move_queued(c, a)
    run.move_queued(a, None)
    with pytest.raises(RunError, match="no longer queued"):
        run.move_queued(b, "gone")
    run._busy = False

    assert [m["text"] for m in run.state["queued"]] == ["c", "b", "a"]
    assert [q[0]["id"] for q in run._queue] == [c, b, a]


def test_stop_holds_the_queue_until_it_is_resumed(logged_in, monkeypatch):
    from ov.agent.engine.run import RunError, runs

    db.create_thread("rhold", "t", Provider.CLAUDE, "m", prompt="x", instance=None, access=Access.READ)
    run = runs.get("rhold")
    run._busy = True
    run.follow_up("later", [], steer=False)
    run.stop()
    run._busy = False
    started: list[str] = []
    monkeypatch.setattr(run, "_spawn", lambda target, *args: started.append(target.__name__))

    run._pick_up_queue()
    assert run.state["queueHeld"] and not started
    with pytest.raises(RunError, match="no running turn"):
        run.steer_queued(run.state["queued"][0]["id"])

    run.resume_queue()
    run._busy = False
    assert not run.state["queueHeld"] and started == ["_run_turn"]


def test_a_reloaded_thread_holds_its_queue(logged_in):
    from ov.agent.engine.run import RunManager, runs

    db.create_thread("rload", "t", Provider.CLAUDE, "m", prompt="x", instance=None, access=Access.READ)
    run = runs.get("rload")
    run._busy = True
    run.follow_up("kept", [], steer=True)
    run._busy = False

    loaded = RunManager().get("rload")
    assert loaded is not None
    assert [(m["text"], m["steer"]) for m in loaded.state["queued"]] == [("kept", False)]
    assert loaded.state["queueHeld"] and loaded._held == {loaded.state["queued"][0]["id"]}


def test_full_access_needs_the_flag_and_falls_back_to_auto_without_it(logged_in, monkeypatch):
    from ov.agent.engine.run import FULL_ACCESS_NEEDS_FLAG, RunError, RunManager

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    started = RunManager()
    started.full_access = True
    run = started.create({"prompt": "hi", "access": Access.FULL}, Provider.COPILOT, "test-model")
    started.require_access(Access.FULL)

    restarted = RunManager()
    with pytest.raises(RunError, match=FULL_ACCESS_NEEDS_FLAG):
        restarted.require_access(Access.FULL)
    loaded = restarted.get(run.id)
    assert loaded is not None and loaded.access == Access.AUTO
    assert db.thread_access(run.id) == Access.AUTO
