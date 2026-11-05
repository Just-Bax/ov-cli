from __future__ import annotations

import threading

import pytest
from helpers.agent import SLOW_POLLS, new_message_id, wait_done, wait_for

from ov.agent.engine.conversation import INTERRUPTED_RESULT
from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db
from ov.agent.storage.models import Access

BREAK = "\n\n"


def test_a_tool_call_left_without_a_result_is_answered_before_the_next_request(logged_in, monkeypatch):
    sent: list[list[dict]] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        sent.append([dict(m) for m in messages])
        return StreamResult(text="Carrying on.")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, "copilot", "test-model")
    wait_done(run)

    call = {"id": "c9", "type": "function", "function": {"name": "ov_sql", "arguments": "{}"}}
    run.messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
    run.emit({"type": "tool", "tool": {"id": "c9", "name": "ov_sql", "label": "SQL", "status": "running"}})
    run._fail(RuntimeError("tool thread died"))

    assert run.state["tools"][-1]["status"] == "error"

    run.follow_up(new_message_id(), "continue", [], steer=False)
    wait_for(lambda: len(sent) == 2)

    last = sent[-1]
    at = next(i for i, m in enumerate(last) if m.get("tool_calls") == [call])
    assert last[at + 1] == {"role": "tool", "tool_call_id": "c9", "content": INTERRUPTED_RESULT}
    assert last[at + 2]["role"] == "user"


def test_the_system_prompt_follows_the_access_mode(logged_in, monkeypatch):
    sent: list[str] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        sent.append(messages[0]["content"])
        return StreamResult(text="ok")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, "copilot", "test-model")
    wait_done(run)
    run.set_access(Access.AUTO)
    run.follow_up(new_message_id(), "go", [], steer=False)
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

    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": "start", "instance": "acme"}, "copilot", "test-model")
    wait_for(lambda: seen)
    run.follow_up(new_message_id(), "later", [], steer=False)
    run.follow_up(new_message_id(), "now", [], steer=True)
    gate.set()
    wait_for(lambda: len(seen) >= 3 and run.state["summary"]["status"] == "done", polls=SLOW_POLLS)

    assert seen[1][-1].endswith(BREAK + "now") and not any(m.endswith("later") for m in seen[1])
    assert seen[2][-1].startswith("[Sent ") and seen[2][-1].endswith(BREAK + "later")
    assert not run.state["queued"] and not run.state["steering"]
    assert [(m["text"], m.get("steer")) for m in run.state["chat"] if m["role"] == "user"] == [
        ("start", None),
        ("now", True),
        ("later", None),
    ]


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

    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": "start", "instance": "acme"}, "copilot", "test-model")
    wait_for(lambda: seen)
    run.follow_up(new_message_id(), "one", [], steer=False)
    run.follow_up(new_message_id(), "two", [], steer=False)
    gate.set()
    wait_for(lambda: len(seen) >= 3 and run.state["summary"]["status"] == "done", polls=SLOW_POLLS)

    assert [m.rsplit(BREAK, 1)[-1] for m in seen[1:]] == ["one", "two"]
    assert not run.state["queued"]


def test_a_steer_reaches_claude_with_the_next_tool_result(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs
    from ov.agent.storage import db

    db.create_thread("rsteer", "t", "claude", "m", instance=None, access=Access.READ)
    run = runs.get("rsteer")
    run._busy = True
    monkeypatch.setattr(run, "call_tool_named", lambda name, args: ("rows", []))
    run.follow_up(new_message_id(), "skip VHMKFBC_PKG", [], steer=False)
    run.follow_up(new_message_id(), "after the turn", [], steer=False)
    steered = run.state["queued"][0]["id"]
    run.send_queued(steered)

    assert run.state["chat"][-1]["text"] == "skip VHMKFBC_PKG" and run.state["chat"][-1]["steer"]
    assert run.state["steering"] == [steered]
    assert [m["text"] for m in run.state["queued"]] == ["after the turn"]

    output, _ = run.call_tool_with_steering("ov_sql", {})
    again, _ = run.call_tool_with_steering("ov_sql", {})
    run._busy = False

    assert output.startswith("rows") and output.endswith("[The user wrote while you worked: skip VHMKFBC_PKG]")
    assert again == "rows"
    assert not run.state["steering"]


def test_an_edited_queued_message_keeps_its_place(logged_in):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import runs

    db.create_thread("redit", "t", "claude", "m", instance=None, access=Access.READ)
    run = runs.get("redit")
    run._busy = True
    run.follow_up(new_message_id(), "first", [], steer=False)
    run.follow_up(new_message_id(), "second", [], steer=False)
    first = run.state["queued"][0]["id"]

    run.edit_queued(first, "first, edited")
    with pytest.raises(RunError, match="needs text or files"):
        run.edit_queued(first, "  ")
    run._busy = False

    assert [m["text"] for m in run.state["queued"]] == ["first, edited", "second"]
    assert run._queue[0][0]["text"] == "first, edited"


def test_queued_messages_can_be_reordered(logged_in):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import runs

    db.create_thread("rmove", "t", "claude", "m", instance=None, access=Access.READ)
    run = runs.get("rmove")
    run._busy = True
    for text in ("a", "b", "c"):
        run.follow_up(new_message_id(), text, [], steer=False)
    a, b, c = (m["id"] for m in run.state["queued"])

    run.move_queued(c, a)
    run.move_queued(a, None)
    with pytest.raises(RunError, match="no longer queued"):
        run.move_queued(b, "gone")
    run._busy = False

    assert [m["text"] for m in run.state["queued"]] == ["c", "b", "a"]
    assert [q[0]["id"] for q in run._queue] == [c, b, a]


def test_stop_holds_the_queue_until_it_is_resumed(logged_in, monkeypatch):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import runs

    db.create_thread("rhold", "t", "claude", "m", instance=None, access=Access.READ)
    run = runs.get("rhold")
    run._busy = True
    run.follow_up(new_message_id(), "now", [], steer=False)
    run.follow_up(new_message_id(), "later", [], steer=False)
    run.stop()
    run._busy = False
    started: list[str] = []
    monkeypatch.setattr(run, "_spawn", lambda target, *args: started.append(target.__name__))

    run._pick_up_queue()
    assert run.state["queueHeld"] and not started

    run.send_queued(run.state["queued"][0]["id"])
    run._busy = False
    assert run.state["chat"][-1]["text"] == "now" and not run.state["chat"][-1].get("steer")
    assert run.state["queueHeld"] and started == ["_run_turn"]
    with pytest.raises(RunError, match="no longer queued"):
        run.send_queued("u_gone_000001")

    run.resume_queue()
    run._busy = False
    assert not run.state["queueHeld"] and started == ["_run_turn", "_run_turn"]


def test_a_steer_left_by_a_stop_waits_and_goes_before_the_next_message(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    db.create_thread("rsteerstop", "t", "claude", "m", instance=None, access=Access.READ)
    run = runs.get("rsteerstop")
    started: list[str] = []
    monkeypatch.setattr(run, "_spawn", lambda target, *args: started.append(target.__name__))
    run.messages.append({"role": "system", "content": "s"})
    run._busy = True
    run.follow_up(new_message_id(), "use the other table", [], steer=True)
    run.stop()
    run._busy = False

    run._pick_up_queue()
    assert not started and len(run.state["steering"]) == 1

    run.follow_up(new_message_id(), "go on", [], steer=False)
    run._busy = False

    texts = [m["content"].rsplit(BREAK, 1)[-1] for m in run.messages if m["role"] == "user"]
    assert texts == ["use the other table", "go on"]
    assert started == ["_run_turn"] and not run.state["steering"]


def test_a_reloaded_thread_holds_its_queue(logged_in):
    from ov.agent.engine.run_manager import RunManager, runs

    db.create_thread("rload", "t", "claude", "m", instance=None, access=Access.READ)
    run = runs.get("rload")
    run._busy = True
    run.follow_up(new_message_id(), "kept", [], steer=False)
    run.follow_up(new_message_id(), "steered", [], steer=True)
    run._busy = False

    loaded = RunManager().get("rload")
    assert loaded is not None
    assert [m["text"] for m in loaded.state["queued"]] == ["kept"] and loaded.state["queueHeld"]
    assert [m["text"] for m, _ in loaded._steers] == ["steered"]


def test_full_access_needs_the_flag_and_falls_back_to_auto_without_it(logged_in, monkeypatch):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import FULL_ACCESS_NEEDS_FLAG, RunManager

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    started = RunManager()
    started.full_access = True
    run = started.create({"prompt": "hi", "access": Access.FULL}, "copilot", "test-model")
    started.require_access(Access.FULL)

    restarted = RunManager()
    with pytest.raises(RunError, match=FULL_ACCESS_NEEDS_FLAG):
        restarted.require_access(Access.FULL)
    loaded = restarted.get(run.id)
    assert loaded is not None and loaded.access == Access.AUTO
    assert db.thread_access(run.id) == Access.AUTO


def test_stop_shows_at_once_and_drops_what_the_turn_still_says(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    release = threading.Event()

    def slow_chat(model, messages, *args, cancel, on_text, **_):
        on_text("Working on it")
        release.wait()
        on_text(" and more")
        return StreamResult(text="Working on it and more")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", slow_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, "copilot", "test-model")
    wait_for(lambda: run.state["chat"] and run.state["chat"][-1]["role"] == "assistant")

    run.stop()
    assert run.state["summary"]["status"] == "cancelled"
    assert run.call_tool({"id": "late", "type": "function", "function": {"name": "ov", "arguments": "{}"}}) == (
        "Stopped by the user."
    )

    release.set()
    wait_for(lambda: not run._busy)
    assert run.state["chat"][-1]["text"] == "Working on it"
    assert run.state["summary"]["status"] == "cancelled"
    assert all(t["id"] != "late" for t in run.state["tools"])


def test_a_follow_up_needs_a_new_well_formed_id(logged_in):
    from ov.agent.engine.run_common import RunError
    from ov.agent.engine.run_manager import runs

    db.create_thread("rids", "t", "claude", "m", instance=None, access=Access.READ)
    run = runs.get("rids")
    run._busy = True

    with pytest.raises(RunError, match="message id looks like"):
        run.follow_up("bad id", "hi", [], steer=False)

    run.follow_up("u_client_000001", "hi", [], steer=False)
    with pytest.raises(RunError, match="already sent"):
        run.follow_up("u_client_000001", "again", [], steer=False)
    assert [m["id"] for m in run.state["queued"]] == ["u_client_000001"]
    run._busy = False
