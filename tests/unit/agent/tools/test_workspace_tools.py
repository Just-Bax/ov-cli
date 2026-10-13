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
    from ov.agent.engine.run import _line_changes
    from ov.agent.tools import tool_named

    ctx = FakeContext(tmp_path)
    tool_named("ws_edit").handler({"path": "module/main.py", "old": "RULE_ID = 1", "new": "RULE_ID = 2\nX = 3"}, ctx)
    tool_named("ws_write").handler({"path": "module/new.py", "content": "a\nb\n"}, ctx)
    assert ctx.edits == [
        ("module/main.py", "RULE_ID = 1", "RULE_ID = 2\nX = 3", False),
        ("module/new.py", "", "a\nb\n", True),
    ]
    assert _line_changes("RULE_ID = 1", "RULE_ID = 2\nX = 3") == (2, 1)
