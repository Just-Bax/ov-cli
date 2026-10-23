from __future__ import annotations

import json
import threading
import time

from helpers.agent import RUN_POLL_SECONDS, SLOW_POLLS, wait_for

from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db


def _wait_for(check):
    wait_for(check, polls=SLOW_POLLS)


def _call(call_id, args, name="ov"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _scripted_model(monkeypatch, replies):
    seen: list[list[dict]] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        seen.append([dict(m) for m in messages])
        reply = replies[min(len(seen), len(replies)) - 1]
        return StreamResult(text=reply.get("text", ""), tool_calls=reply.get("calls") or [])

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    return seen


def _slow_ov(monkeypatch, gate):
    def fake_run_ov(*args, cancel=None, **_):
        while not gate.is_set():
            if cancel is not None and cancel.is_set():
                return OvResult(1, "", "killed")
            time.sleep(RUN_POLL_SECONDS)
        return OvResult(0, "slow result\n", "")

    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", fake_run_ov)


def _tool(run, tool_id):
    return next(t for t in run.state["tools"] if t["id"] == tool_id)


def test_a_background_call_returns_at_once_and_wakes_the_idle_run_with_its_result(logged_in, monkeypatch):
    gate = threading.Event()
    _slow_ov(monkeypatch, gate)
    seen = _scripted_model(
        monkeypatch,
        [
            {"calls": [_call("c1", {"args": ["request", "GET", "/v3/x"], "background": True})]},
            {"text": "Started it, I will wait."},
            {"text": "The slow call finished."},
        ],
    )

    from ov.agent.engine.run import BACKGROUND_STARTED, runs

    run = runs.create({"access": "read", "prompt": "go", "instance": "acme"}, "copilot", "test-model")
    _wait_for(lambda: len(seen) == 2 and not run._busy)
    assert seen[1][-1]["content"] == BACKGROUND_STARTED.format(label=_tool(run, "c1")["label"])
    assert run.state["summary"]["status"] == "running"
    assert _tool(run, "c1")["backgroundedAt"] == _tool(run, "c1")["startedAt"]

    gate.set()
    _wait_for(lambda: run.state["summary"]["status"] == "done" and len(seen) == 3)
    assert "[Background task finished:" in seen[2][-1]["content"] and "slow result" in seen[2][-1]["content"]
    assert _tool(run, "c1")["status"] == "ok"

    statuses = [e["event"] for e in db.load_events(run.id) if e["event"]["type"] == "status"]
    assert any(s.get("wokenBy") == "c1" for s in statuses)


def test_a_running_call_can_be_moved_to_the_background(logged_in, monkeypatch):
    gate = threading.Event()
    _slow_ov(monkeypatch, gate)
    seen = _scripted_model(
        monkeypatch,
        [
            {"calls": [_call("c1", {"args": ["request", "GET", "/v3/x"]})]},
            {"text": "Moved on."},
            {"text": "Got it."},
        ],
    )

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "go", "instance": "acme"}, "copilot", "test-model")
    _wait_for(lambda: any(t["id"] == "c1" for t in run.state["tools"]))
    run.move_to_background("c1")
    _wait_for(lambda: len(seen) >= 2)
    assert "Running in the background" in seen[1][-1]["content"]

    gate.set()
    _wait_for(lambda: len(seen) == 3 and run.state["summary"]["status"] == "done")
    assert "slow result" in seen[2][-1]["content"]


def test_stopping_a_foreground_call_keeps_the_turn_going(logged_in, monkeypatch):
    gate = threading.Event()
    _slow_ov(monkeypatch, gate)
    seen = _scripted_model(
        monkeypatch,
        [{"calls": [_call("c1", {"args": ["request", "GET", "/v3/x"]})]}, {"text": "Understood."}],
    )

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "go", "instance": "acme"}, "copilot", "test-model")
    _wait_for(lambda: any(t["id"] == "c1" for t in run.state["tools"]))
    run.stop_tool("c1")
    _wait_for(lambda: run.state["summary"]["status"] == "done")
    assert seen[1][-1]["content"] == "Error: Stopped by the user."
    assert _tool(run, "c1")["status"] == "error" and _tool(run, "c1")["stoppedAt"]


def test_stopping_the_run_stops_background_tasks_without_waking_it(logged_in, monkeypatch):
    gate = threading.Event()
    _slow_ov(monkeypatch, gate)
    seen = _scripted_model(
        monkeypatch,
        [
            {"calls": [_call("c1", {"args": ["request", "GET", "/v3/x"], "background": True})]},
            {"text": "Waiting."},
        ],
    )

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "go", "instance": "acme"}, "copilot", "test-model")
    _wait_for(lambda: len(seen) == 2 and not run._busy)
    run.stop()
    _wait_for(lambda: _tool(run, "c1")["status"] == "error")
    assert run.state["summary"]["status"] == "cancelled"
    assert _tool(run, "c1")["stoppedAt"]
    time.sleep(0.3)
    assert len(seen) == 2


def test_a_background_task_cannot_ask_for_approval(tmp_path):
    import pytest

    from ov.agent.engine.tasks import Task, TaskContext
    from ov.agent.tools.base import Approval, ToolError

    class Owner:
        def ask_approval(self, *args):
            return Approval(True, "")

    task = Task({"id": "c1", "label": "x"}, 1)
    context = TaskContext(Owner(), task)
    assert context.ask_approval("ok?", "detail").approved
    task.backgrounded_at = 2
    with pytest.raises(ToolError, match="foreground"):
        context.ask_approval("ok?", "detail")
    with pytest.raises(ToolError, match="foreground"):
        context.ask_user([{"question": "which?"}])


def test_every_tool_but_the_silent_ones_offers_background():
    from ov.agent.tools import TOOLS

    for tool in TOOLS:
        assert ("background" in tool.spec["function"]["parameters"]["properties"]) is not tool.silent
