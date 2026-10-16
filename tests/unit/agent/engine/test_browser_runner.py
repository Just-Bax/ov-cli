from __future__ import annotations

import asyncio
from pathlib import Path

from claude_agent_sdk import ResultMessage

from ov.agent.engine import browser_runner
from ov.agent.engine.cancel import Cancel
from ov.agent.storage.models import Provider

REPORT = "Result: done\nSteps: looked\nSeen: the grid\nProblem: none"


class FakeRun:
    provider = Provider.CLAUDE

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.usage: list[str] = []

    def record_step_usage(self, model, usage):
        self.usage.append(model)


class FakeClient:
    def __init__(self, options):
        self.options = options

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, goal):
        self.goal = goal

    async def interrupt(self):
        return None

    async def receive_response(self):
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            total_cost_usd=0.01,
            result=REPORT,
        )


def test_the_runner_resolves_its_options_before_starting_its_event_loop(tmp_path, monkeypatch):
    def effort_outside_a_loop(model, wanted):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise AssertionError("effort_for ran inside the runner's event loop")

    monkeypatch.setattr("ov.agent.integrations.claude.effort_for", effort_outside_a_loop)
    monkeypatch.setattr("ov.agent.integrations.claude.cli_path", lambda: "claude")
    monkeypatch.setattr(browser_runner, "ClaudeSDKClient", FakeClient)

    run = FakeRun(tmp_path)
    assert browser_runner.drive(run, "haiku", "Open the grid", Cancel()) == REPORT
    assert run.usage == ["haiku"]
