from __future__ import annotations

import threading
import time

from helpers.agent import wait_done

from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage.models import Provider

BREAK = chr(10) * 2


def test_a_tool_call_left_without_a_result_is_answered_before_the_next_request(logged_in, monkeypatch):
    sent: list[list[dict]] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        sent.append([dict(m) for m in messages])
        return StreamResult(text="Carrying on.")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)
    call = {"id": "c9", "type": "function", "function": {"name": "ov_sql", "arguments": "{}"}}
    run._messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
    run.emit({"type": "tool", "tool": {"id": "c9", "name": "ov_sql", "label": "SQL", "status": "running"}})
    run._fail(RuntimeError("tool thread died"))
    assert run.state["tools"][-1]["status"] == "error"

    run.follow_up("continue", [])
    for _ in range(100):
        if len(sent) == 2:
            break
        time.sleep(0.05)
    last = sent[-1]
    at = next(i for i, m in enumerate(last) if m.get("tool_calls") == [call])
    assert last[at + 1] == {"role": "tool", "tool_call_id": "c9", "content": "Error: interrupted."}
    assert last[at + 2]["role"] == "user"


def test_the_system_prompt_follows_write_access(logged_in, monkeypatch):
    sent: list[str] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        sent.append(messages[0]["content"])
        return StreamResult(text="ok")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)
    run.set_write_access(True)
    run.follow_up("go", [])
    for _ in range(100):
        if len(sent) == 2:
            break
        time.sleep(0.05)
    assert "currently OFF" in sent[0]
    assert "currently ON" in sent[1]


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

    run = runs.create({"prompt": "start", "instance": "acme"}, Provider.COPILOT, "test-model")
    for _ in range(100):
        if seen:
            break
        time.sleep(0.05)
    run.follow_up("later", [], steer=False)
    run.follow_up("now", [], steer=True)
    gate.set()
    for _ in range(200):
        if len(seen) >= 3 and run.state["summary"]["status"] == "done":
            break
        time.sleep(0.05)

    assert seen[1][-1].endswith(BREAK + "now") and not any(m.endswith("later") for m in seen[1])
    assert seen[2][-1].startswith("[Sent ") and seen[2][-1].endswith(BREAK + "later")
    assert not run.state["queued"]
