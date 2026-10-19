from __future__ import annotations

import json

from helpers.agent import wait_done, wait_for
from sqlalchemy import select

from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult, Usage
from ov.agent.storage import db, models
from ov.agent.storage.models import Access, Provider


def test_a_run_streams_calls_tools_and_finishes(logged_in, monkeypatch):
    replies = iter(
        [
            StreamResult(
                text="Checking.",
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "ov", "arguments": '{"args": ["api", "tags"]}'},
                    }
                ],
            ),
            StreamResult(text="All good."),
        ]
    )

    def fake_chat(*args, cancel, on_text, **_):
        reply = next(replies)
        on_text(reply.text)
        return reply

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(0, "users\n", ""))

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "what tags?", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)

    assert [t["status"] for t in run.state["tools"]] == ["ok"]
    assert run.state["chat"][-1]["text"] == "All good."
    assert db.list_threads()[0]["status"] == "done"


def test_dangling_tool_calls_get_stub_results():
    from ov.agent.engine.run import _answered

    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "ok"},
    ]
    fixed = _answered(messages)
    assert [m.get("tool_call_id") for m in fixed[2:]] == ["a", "b"]


def test_cut_off_tool_arguments_never_reach_copilot_again(logged_in, monkeypatch):
    cut = '{"path": "widget.html", "content": "<html><body>'
    replies = iter(
        [
            StreamResult(
                text="Writing.",
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "ov", "arguments": cut}}],
            ),
            StreamResult(text="Done in parts."),
        ]
    )
    sent: list[list[dict]] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        sent.append(json.loads(json.dumps(messages)))
        reply = next(replies)
        on_text(reply.text)
        return reply

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "build it", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)

    second = sent[1]
    call = next(m for m in second if m.get("tool_calls"))["tool_calls"][0]
    assert call["function"]["arguments"] == "{}"
    result = next(m for m in second if m["role"] == "tool")["content"]
    assert "cut off" in result and "in parts" in result


def test_status_changes_reach_the_status_feed(logged_in):
    from ov.agent.engine.run import runs, status_feed

    db.create_thread("rfeed", "Feed run", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    run = runs.get("rfeed")
    channel, unsubscribe = status_feed.subscribe()
    try:
        run._set_status("waiting")
        run._set_status("waiting")
        run._set_status("done")
        changes = [channel.get_nowait(), channel.get_nowait()]
    finally:
        unsubscribe()
    assert changes == [
        {"kind": "status", "id": "rfeed", "status": "waiting", "title": "Feed run"},
        {"kind": "status", "id": "rfeed", "status": "done", "title": "Feed run"},
    ]
    assert channel.empty()


def test_streamed_text_is_stored_as_one_message_and_reloads(logged_in, monkeypatch):
    def fake_chat(*args, cancel, on_text, **_):
        on_text("All ")
        on_text("good.")
        return StreamResult(text="All good.")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_for(lambda: run.state["summary"]["status"] in ("done", "error"))

    kinds = [e["event"]["type"] for e in db.load_events(run.id)]
    assert "text" not in kinds
    assert kinds.count("message") == 1
    runs._runs.pop(run.id)
    assert runs.get(run.id).state["chat"][-1]["text"] == "All good."


def test_resuming_a_stream_sends_the_partial_message(logged_in):
    from ov.agent.engine.run import runs

    db.create_thread("rlive", "t", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    run = runs.get("rlive")
    run.stream_text("a1", "Hel")
    channel, unsubscribe, backlog = run.resume(run.seq)
    try:
        assert backlog[-1]["live"] is True
        assert backlog[-1]["event"]["text"] == "Hel"
        run.stream_text("a1", "lo")
        assert channel.get_nowait()["event"] == {"type": "text", "messageId": "a1", "delta": "lo"}
        run.commit_text("a1")
        committed = channel.get_nowait()
    finally:
        unsubscribe()
    assert committed["event"]["text"] == "Hello"
    assert "live" not in committed


def test_idle_runs_are_dropped_from_memory_but_never_while_in_use(logged_in):
    from ov.agent.engine.run import EVICT_GRACE_MS, MAX_CACHED_RUNS, runs

    runs._runs.clear()
    held = []
    for n in range(MAX_CACHED_RUNS + 3):
        db.create_thread(f"revict{n}", "t", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
        held.append(runs.get(f"revict{n}"))
    assert all(runs.get(f"revict{n}") is held[n] for n in range(MAX_CACHED_RUNS + 3))

    for run in held:
        run.touched -= EVICT_GRACE_MS + 1
    runs.get("revict0")
    assert len(runs._runs) <= MAX_CACHED_RUNS + 1
    assert "revict0" in runs._runs and "revict1" not in runs._runs


def test_a_run_records_what_each_request_cost(logged_in, monkeypatch):
    usage = Usage(tokens={"input": 1000, "output": 10}, nano=1_500_000_000)
    replies = iter(
        [
            StreamResult(
                text="Checking.",
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "ov", "arguments": '{"args": []}'}}],
                usage=usage,
            ),
            StreamResult(text="Done.", usage=usage),
        ]
    )
    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", lambda *a, cancel, on_text, **_: next(replies))
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    monkeypatch.setattr("ov.agent.integrations.copilot.prompt_limit", lambda _: 200_000)
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(0, "ok\n", ""))

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)

    assert run.state["summary"]["cost"] == {"credits": 3.0, "usd": 0.0, "requests": 2}
    assert run.state["context"] == {"tokens": 1010, "limit": 200_000, "compactAt": 180_000}
    assert db.list_threads()[0]["cost"] == {"credits": 3.0, "usd": 0.0, "requests": 2}
    cost = db.thread_cost(run.id)
    assert cost["tokens"] == {"input": 2000, "output": 20}
    with db._begin() as conn:
        kinds = list(
            conn.scalars(select(models.Usage.kind).where(models.Usage.thread_id == run.id).order_by(models.Usage.id))
        )
    assert kinds == ["turn", "step"]


def test_an_empty_reply_is_asked_for_once(logged_in, monkeypatch):
    replies = iter([StreamResult(text=""), StreamResult(text="Here it is.")])
    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", lambda *a, cancel, on_text, **_: next(replies))
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)
    assert run._messages[-2]["content"].startswith("[Your last reply was empty")
    assert run._messages[-1]["content"] == "Here it is."
