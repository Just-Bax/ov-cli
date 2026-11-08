from __future__ import annotations

import pytest
from helpers.agent import FakeContext

from ov.agent.storage import db


def test_workspace_tools_are_offered_only_with_a_folder(tmp_path):
    from ov.agent.tools import tool_specs

    assert "ws_run" not in {s["function"]["name"] for s in tool_specs()}
    db.save_preferences({"workspace": str(tmp_path)})
    assert "ws_run" in {s["function"]["name"] for s in tool_specs()}
    with pytest.raises(ValueError):
        db.save_preferences({"workspace": str(tmp_path / "missing")})
    db.save_preferences({"workspace": ""})


def test_workspace_edits_are_recorded_for_the_changes_view(workspace, tmp_path):
    from ov.agent.engine.run_tools import _line_changes
    from ov.agent.tools import tool_named

    ctx = FakeContext(tmp_path, write=True)
    tool_named("ws_edit").handler({"path": "module/main.py", "old": "RULE_ID = 1", "new": "RULE_ID = 2\nX = 3"}, ctx)
    tool_named("ws_write").handler({"path": "module/new.py", "content": "a\nb\n"}, ctx)
    assert ctx.edits == [
        ("module/main.py", "alpha\nRULE_ID = 1\n", "alpha\nRULE_ID = 2\nX = 3\n", False),
        ("module/new.py", "", "a\nb\n", True),
    ]
    assert _line_changes("RULE_ID = 1", "RULE_ID = 2\nX = 3") == (2, 1)


def test_workspace_edits_need_allow_changes(workspace, tmp_path):
    from ov.agent.tools import tool_named
    from ov.agent.tools.base import ToolError

    ctx = FakeContext(tmp_path)
    with pytest.raises(ToolError, match="this thread is Read-only"):
        tool_named("ws_edit").handler({"path": "module/main.py", "old": "RULE_ID = 1", "new": "x"}, ctx)
    with pytest.raises(ToolError, match="this thread is Read-only"):
        tool_named("ws_write").handler({"path": "module/new.py", "content": "a"}, ctx)
    assert ctx.edits == [] and "RULE_ID = 1" in (workspace / "module" / "main.py").read_text(encoding="utf-8")


def test_a_command_is_judged_with_the_script_it_runs(workspace, tmp_path, monkeypatch):
    from ov.agent import workspace as project
    from ov.agent.tools import tool_named

    (workspace / "push.py").write_text("password = 'hunter22'\nprint('hi')", encoding="utf-8")
    monkeypatch.setattr(project, "run", lambda command, folder, timeout, cancel: "hi")
    ctx = FakeContext(tmp_path, write=True)

    assert tool_named("ws_run").handler({"command": "python push.py"}, ctx) == "hi"
    assert ctx.scripts == {"push.py": "password = '***'\nprint('hi')"}


@pytest.mark.parametrize(("auto", "asked"), [(False, True), (True, False)])
def test_ask_first_asks_before_every_command_that_changes_something(workspace, tmp_path, monkeypatch, auto, asked):
    from ov.agent import workspace as project
    from ov.agent.engine.guard import Effect
    from ov.agent.tools import tool_named

    monkeypatch.setattr(project, "run", lambda command, folder, timeout, cancel: "built")
    ctx = FakeContext(tmp_path, write=True, auto=auto, effects={"npm run build": Effect.CHANGE})

    assert tool_named("ws_run").handler({"command": "npm run build"}, ctx) == "built"
    assert bool(ctx.asked) is asked


def test_the_agent_cannot_write_repository_internals(workspace, tmp_path):
    from ov.agent.tools import tool_named
    from ov.agent.tools.base import ToolError

    ctx = FakeContext(tmp_path, write=True)
    for path in (".git/config", "module/.git/hooks/pre-commit"):
        with pytest.raises(ToolError, match="repository internals"):
            tool_named("ws_write").handler({"path": path, "content": "x"}, ctx)
