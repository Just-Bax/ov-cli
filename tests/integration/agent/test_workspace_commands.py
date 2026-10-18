from __future__ import annotations

import time

import pytest
from helpers.agent import FakeContext

CHILD_SECONDS = 4
COMMAND_TIMEOUT_SECONDS = 1
KILL_CHECK_SECONDS = 5
MAX_STOP_SECONDS = 15


def test_ws_run_gates_commands_by_their_judged_effect(workspace, tmp_path):
    from ov.agent.engine.guard import Effect
    from ov.agent.tools import tool_named
    from ov.agent.tools.base import ToolError

    effects = {"git commit -m x": Effect.CHANGE, "git push": Effect.OUTSIDE}
    tool = tool_named("ws_run")
    reading = FakeContext(tmp_path, effects=effects)
    assert "git version" in tool.handler({"command": "git --version", "cwd": "module"}, reading)
    assert reading.asked == [] and reading.judged == ["git --version"]

    with pytest.raises(ToolError, match="Nothing to run"):
        tool.handler({"command": "echo skip"}, reading)

    for command in ("git commit -m x", "git push"):
        with pytest.raises(ToolError, match="this thread is Read-only"):
            tool.handler({"command": command}, reading)

    assert reading.asked == []

    writing = FakeContext(tmp_path, write=True, approve="Reject", effects=effects)
    with pytest.raises(ToolError, match="rejected"):
        tool.handler({"command": "git push"}, writing)
    assert writing.asked == ["the workspace root> git push"]


def test_a_cancelled_command_stops_its_children(workspace):
    from ov.agent import workspace as project
    from ov.agent.engine.cancel import Cancel

    marker = project.root() / "child-alive.txt"
    script = project.root() / "child.py"
    script.write_text(f"import time\ntime.sleep({CHILD_SECONDS})\nopen({str(marker)!r}, 'w').write('x')\n")
    started = time.monotonic()
    project.run(f'python "{script}"; python "{script}"', "", COMMAND_TIMEOUT_SECONDS, Cancel())
    assert time.monotonic() - started < MAX_STOP_SECONDS

    time.sleep(KILL_CHECK_SECONDS)
    assert not marker.exists()
