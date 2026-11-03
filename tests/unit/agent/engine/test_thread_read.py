from __future__ import annotations

import pytest
from helpers.agent import wait_done

from ov.agent.integrations.copilot import StreamResult
from ov.agent.tools import tool_named

REPLY = "Rule 100026030 is fixed on dev-lumen."


def test_a_thread_reads_another_thread_by_id_or_link(logged_in, monkeypatch):
    def fake_chat(*args, on_text, **_):
        on_text(REPLY)
        return StreamResult(text=REPLY)

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run_manager import runs

    done = runs.create({"access": "read", "prompt": "fix the rule", "instance": "acme"}, "copilot", "test-model")
    reader = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, "copilot", "test-model")
    wait_done(done)
    wait_done(reader)
    read = tool_named("thread_read").handler

    by_id = read({"thread": done.id}, reader)
    by_link = read({"thread": f"http://127.0.0.1:5180/#/thread/{done.id}"}, reader)

    assert "fix the rule" in by_id and REPLY in by_id
    assert by_link == by_id
    with pytest.raises(Exception, match="That is this thread"):
        read({"thread": reader.id}, reader)
    with pytest.raises(Exception, match="No thread zzz"):
        read({"thread": "zzz"}, reader)
