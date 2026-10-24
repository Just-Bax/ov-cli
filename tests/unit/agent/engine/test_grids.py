from __future__ import annotations

import pytest
from helpers.agent import wait_done, wait_for

from ov.agent.engine.run_common import RunError
from ov.agent.integrations.copilot import StreamResult
from ov.agent.tools import grid as grids


@pytest.fixture
def run(logged_in, monkeypatch):
    replies: list[str] = []

    def fake_chat(model, messages, *args, cancel, on_text, **_):
        replies.append(str(messages[-1]["content"]))
        return StreamResult(text="ok")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run_manager import runs

    started = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, "copilot", "test-model")
    wait_done(started)
    started.replies = replies
    return started


def test_a_sql_grid_runs_again_on_request(run, monkeypatch):
    source = {"kind": "sql", "query": "select 1 n from dual", "limit": 10}
    run.emit({"type": "grid", "grid": {"id": "g1", "title": "One", "instance": "acme", "rows": [], "source": source}})
    monkeypatch.setattr(grids, "fetch", lambda alias, src, cancel: ([{"N": "1"}], 1))

    run.rerun_grid("g1")

    wait_for(lambda: run.state["grids"][0].get("loading") is False)
    shown = run.state["grids"][0]
    assert shown["rows"] == [{"N": "1"}] and shown["total"] == 1 and shown["error"] is None


def test_a_failed_rerun_shows_its_error(run, monkeypatch):
    source = {"kind": "sql", "query": "select x from y", "limit": 10}
    run.emit({"type": "grid", "grid": {"id": "g1", "title": "Bad", "instance": "acme", "rows": [], "source": source}})

    def broken(alias, src, cancel):
        raise RuntimeError("ORA-00942: table or view does not exist")

    monkeypatch.setattr(grids, "fetch", broken)
    run.rerun_grid("g1")

    wait_for(lambda: run.state["grids"][0].get("loading") is False)
    assert run.state["grids"][0]["error"] == "ORA-00942: table or view does not exist"


def test_only_finished_changes_can_be_reverted(run):
    change = {"state": "done", "updated": 2}
    run.emit({"type": "grid", "grid": {"id": "g2", "title": "Hold sites", "rows": [], "change": change}})
    run.emit({"type": "grid", "grid": {"id": "g3", "title": "Saved", "rows": []}})

    with pytest.raises(RunError, match="Ask the agent to load it again"):
        run.rerun_grid("g3")
    with pytest.raises(RunError, match="Only a finished data change"):
        run.revert_grid("g3")

    run.revert_grid("g2")
    wait_for(lambda: any("revert g2" in r for r in run.replies))
