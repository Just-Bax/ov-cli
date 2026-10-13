from __future__ import annotations

import time

import pytest
from helpers.agent import FakeContext


def test_ws_run_asks_before_risky_commands(workspace, tmp_path):
    from ov.agent.tools import tool_named
    from ov.agent.tools.base import ToolError

    ctx = FakeContext(tmp_path, approve="Reject")
    tool = tool_named("ws_run")
    assert "git version" in tool.handler({"command": "git --version", "cwd": "module"}, ctx)
    assert ctx.asked == []
    with pytest.raises(ToolError, match="Nothing to run"):
        tool.handler({"command": "echo skip"}, ctx)
    with pytest.raises(ToolError, match="rejected"):
        tool.handler({"command": "git push"}, ctx)
    assert ctx.asked == ["the workspace root> git push"]


def test_a_cancelled_command_stops_its_children(workspace):
    from ov.agent import workspace as project
    from ov.agent.engine.cancel import Cancel

    marker = project.root() / "child-alive.txt"
    script = project.root() / "child.py"
    script.write_text(f"import time\ntime.sleep(4)\nopen({str(marker)!r}, 'w').write('x')\n")
    started = time.monotonic()
    project.run(f'python "{script}"; python "{script}"', "", 1, Cancel())
    assert time.monotonic() - started < 15
    time.sleep(5)
    assert not marker.exists()
