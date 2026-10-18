from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from claude_agent_sdk import ResultMessage, StreamEvent, SystemMessage, UserMessage
from helpers.agent import RUN_POLL_SECONDS, SLOW_POLLS, wait_for

from ov.agent.storage import db
from ov.agent.storage.models import Provider

SESSION_UUID_LENGTH = 36
CONTEXT_USAGE = {"totalTokens": 52_000, "rawMaxTokens": 200_000, "autoCompactThreshold": 167_000}

BREAK = "\n\n"


def _wait_for(check):
    wait_for(check, polls=SLOW_POLLS)


def _text_events(text: str) -> list[StreamEvent]:
    events = [
        {"type": "message_start"},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
        {"type": "message_stop"},
    ]
    return [StreamEvent(uuid=f"e{i}", session_id="s", event=e) for i, e in enumerate(events)]


def _result(cost: float = 0.25) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s",
        total_cost_usd=cost,
        usage={"input_tokens": 10, "output_tokens": 3, "cache_read_input_tokens": 5},
    )


class FakeClient:
    sessions: ClassVar[list[Any]] = []
    replies: ClassVar[list[Any]] = []
    prompts: ClassVar[list[list[dict[str, Any]]]] = []
    tool_reply: ClassVar[Any] = None

    def __init__(self, options: Any) -> None:
        self.options = options
        FakeClient.sessions.append(options)

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def query(self, prompt: Any, session_id: str = "default") -> None:
        if isinstance(prompt, str):
            FakeClient.prompts.append([{"type": "text", "text": prompt}])
            return
        async for message in prompt:
            FakeClient.prompts.append(message["message"]["content"])

    async def get_context_usage(self) -> dict[str, Any]:
        return CONTEXT_USAGE

    async def receive_response(self):
        script = FakeClient.replies.pop(0)
        yield UserMessage(content="prompt", uuid=f"p{len(FakeClient.prompts)}")
        for step in script:
            if callable(step):
                await step(self.options)
                continue
            yield step

    async def interrupt(self) -> None:
        return None


def _transcript(session: str, directory: str) -> list[Any]:
    return [SimpleNamespace(uuid=f"tail-{len(FakeClient.prompts)}")] if FakeClient.prompts else []


@pytest.fixture
def claude_thread(logged_in, monkeypatch):
    FakeClient.sessions, FakeClient.replies, FakeClient.prompts = [], [], []
    monkeypatch.setattr("ov.agent.engine.claude_loop.ClaudeSDKClient", FakeClient)
    monkeypatch.setattr("ov.agent.engine.claude_loop.get_session_messages", _transcript)
    monkeypatch.setattr("ov.agent.integrations.claude.cli_path", lambda: "claude")
    monkeypatch.setattr("ov.agent.integrations.claude.list_models", lambda: [{"id": "opus", "reasoning": ["high"]}])
    monkeypatch.setattr("ov.agent.integrations.claude.complete", lambda *a: ("Claude thread", None))
    db.save_preferences({"provider": "claude", "reasoning": "high"})


def _start(prompt: str):
    from ov.agent.engine.run import runs

    return runs.create({"access": "read", "prompt": prompt, "instance": "acme"}, Provider.CLAUDE, "opus")


def test_a_claude_thread_streams_text_records_usage_and_its_session(claude_thread):
    FakeClient.replies = [[*_text_events("Hello from Claude."), _result()]]
    run = _start("hi")
    _wait_for(lambda: run.state["summary"]["status"] == "done")

    options = FakeClient.sessions[0]
    assert options.tools == [] and options.setting_sources == []
    assert options.allowed_tools == ["mcp__ov__*"] and "ov" in options.mcp_servers
    assert options.model == "opus" and options.effort == "high"
    assert len(options.session_id) == SESSION_UUID_LENGTH and options.resume is None
    assert FakeClient.prompts[0][0]["text"].startswith("[Sent ") and FakeClient.prompts[0][0]["text"].endswith(
        BREAK + "hi"
    )
    assert [m["text"] for m in run.state["chat"] if m["role"] == "assistant"] == ["Hello from Claude."]
    assert run.state["summary"]["cost"] == {"credits": 0.0, "usd": 0.25, "requests": 1}
    assert run.state["claude"]["session"] == options.session_id
    assert run.state["claude"]["turns"]["u_start"]["prompt"] == "p1"


def test_a_follow_up_resumes_the_same_claude_session(claude_thread):
    FakeClient.replies = [[_result()], [*_text_events("Second."), _result()]]
    run = _start("first")
    _wait_for(lambda: run.state["summary"]["status"] == "done")
    first = FakeClient.sessions[0].session_id

    run.follow_up("second", [], steer=False)
    _wait_for(lambda: len(FakeClient.sessions) == 2 and run.state["summary"]["status"] == "done" and not run._busy)
    assert FakeClient.sessions[1].resume == first and FakeClient.sessions[1].session_id is None
    assert FakeClient.prompts[1][0]["text"].endswith(BREAK + "second")


def test_retrying_a_claude_turn_forks_the_session_before_it(claude_thread, monkeypatch):
    FakeClient.replies = [[_result()], [_result()], [_result()]]
    run = _start("first")
    _wait_for(lambda: run.state["summary"]["status"] == "done")
    run.follow_up("second", [], steer=False)
    _wait_for(lambda: len(FakeClient.sessions) == 2 and not run._busy)
    second = next(m["id"] for m in run.state["chat"] if m["text"] == "second")
    anchor = run.state["claude"]["turns"][second]

    run.retry(second)
    _wait_for(lambda: len(FakeClient.sessions) == 3 and not run._busy)
    fork = FakeClient.sessions[2]
    assert anchor["before"] == "tail-1" and anchor["prompt"] == "p2"
    assert fork.resume == anchor["session"] and fork.fork_session
    assert (fork.resume_session_at, fork.resume_drops_turn) == ("tail-1", "p2")
    assert fork.session_id != anchor["session"]
    assert run.state["claude"]["session"] == fork.session_id
    assert anchor["spentBefore"] == 0.25 and run.state["summary"]["cost"]["usd"] == 0.25


def test_claude_calls_our_tools_through_the_in_process_server(claude_thread):
    import asyncio

    from ov.agent.engine import claude_loop

    started: dict[str, Any] = {}

    async def call_skill(options):
        assert "ov" in options.mcp_servers
        while "run" not in started:
            await asyncio.sleep(RUN_POLL_SECONDS)
        FakeClient.tool_reply = await claude_loop.tool_handler(started["run"], "skill_read")({"name": "ov-cli"})

    FakeClient.replies = [[call_skill, *_text_events("Read it."), _result()]]
    run = _start("read the ov-cli skill")
    started["run"] = run
    _wait_for(lambda: run.state["summary"]["status"] == "done")

    tool = next(t for t in run.state["tools"] if t["name"] == "skill_read")
    assert tool["status"] == "ok" and tool["startedAt"]
    reply = FakeClient.tool_reply
    assert not reply["is_error"] and reply["content"][0]["text"].startswith("# OV CLI")


def test_images_become_claude_image_blocks():
    from ov.agent.engine.claude_loop import content_blocks

    blocks = content_blocks(
        [
            "plain",
            [
                {"type": "text", "text": "see"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
            ],
        ]
    )
    assert blocks == [
        {"type": "text", "text": "plain"},
        {"type": "text", "text": "see"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
    ]


def test_claude_account_comes_from_the_cli_only(monkeypatch):
    from ov.agent.integrations import claude

    class Done:
        stdout = json.dumps({"loggedIn": True, "email": "a@b.c", "subscriptionType": "max", "authMethod": "claude.ai"})
        stderr = ""

    monkeypatch.setattr(claude.shutil, "which", lambda _: "claude")
    monkeypatch.setattr(claude.subprocess, "run", lambda args, **_: Done() if args[1:] == ["auth", "status"] else None)
    claude.forget_account()
    account = claude.account()
    assert account["signedIn"] and account["email"] == "a@b.c" and account["plan"] == "max"

    monkeypatch.setattr(claude.shutil, "which", lambda _: None)
    claude.forget_account()
    assert claude.account() == {"installed": False, "signedIn": False}


def test_switching_provider_picks_that_providers_models(ov_home, monkeypatch):
    from ov.agent.integrations import providers

    monkeypatch.setattr(
        "ov.agent.integrations.copilot.list_models",
        lambda: [{"id": "gpt-6"}, {"id": "claude-opus-5"}, {"id": "claude-opus-5.5"}, {"id": "claude-sonnet-5"}],
    )
    assert providers.default_models(Provider.CLAUDE) == ("opus", "haiku")
    monkeypatch.setattr("ov.agent.integrations.copilot.user", lambda: None)
    assert providers.default_models(Provider.COPILOT) == (None, None)
    monkeypatch.setattr("ov.agent.integrations.copilot.user", lambda: "someone")
    assert providers.default_models(Provider.COPILOT) == ("claude-opus-5.5", None)
    with pytest.raises(ValueError, match="provider must be one of"):
        db.save_preferences({"provider": "openai"})


def test_claude_reports_session_totals_so_each_turn_records_only_its_own_cost(claude_thread):
    FakeClient.replies = [[_result(0.5)], [_result(0.75)]]
    run = _start("first")
    _wait_for(lambda: run.state["summary"]["status"] == "done")
    run.follow_up("second", [], steer=False)
    _wait_for(lambda: len(FakeClient.sessions) == 2 and not run._busy)
    assert run.state["summary"]["cost"]["usd"] == 0.75
    assert run.state["claude"]["spent"] == 0.75


def test_a_resent_message_gets_one_fresh_time_stamp():
    from ov.agent.engine.prompt import stamped

    once = stamped("check it")
    again = stamped(once)
    assert once.startswith("[Sent ") and once.endswith("\n\ncheck it")
    assert again.count("[Sent ") == 1
    parts = stamped([{"type": "text", "text": "see"}, {"type": "image_url", "image_url": {"url": "data:x"}}])
    assert parts[0]["text"].endswith("\n\nsee") and parts[1]["type"] == "image_url"


def test_deleting_a_claude_thread_deletes_its_claude_code_transcripts(claude_thread, monkeypatch):
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ov.agent.engine.claude_loop.delete_session", lambda session, directory: deleted.append((session, directory))
    )
    FakeClient.replies = [[_result()]]
    run = _start("hi")
    _wait_for(lambda: run.state["summary"]["status"] == "done")
    session = run.state["claude"]["session"]

    from ov.agent.engine.run import runs

    runs.delete(run.id)
    assert deleted == [(session, str(run.work_dir))]


def _compacted(trigger: str) -> list[SystemMessage]:
    return [
        SystemMessage(subtype="status", data={"status": "compacting"}),
        SystemMessage(subtype="status", data={"status": None, "compact_result": "success"}),
        SystemMessage(
            subtype="compact_boundary",
            data={"compact_metadata": {"trigger": trigger, "pre_tokens": 170_000, "post_tokens": 9_000}},
        ),
    ]


def test_claude_compacts_at_the_chosen_window_and_shows_it_in_the_thread(claude_thread):
    db.save_preferences({"compactWindow": 200_000})
    FakeClient.replies = [[*_compacted("auto"), *_text_events("Carrying on."), _result()]]
    run = _start("a long investigation")
    _wait_for(lambda: run.state["summary"]["status"] == "done")

    assert FakeClient.sessions[0].env == {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000"}
    [compacted] = run.state["compactions"]
    assert compacted["status"] == "done" and compacted["trigger"] == "auto"
    assert (compacted["before"], compacted["after"]) == (170_000, 9_000)
    assert {"kind": "compact", "id": compacted["id"]} in run.state["items"]
    assert run.state["context"] == {"tokens": 52_000, "limit": 200_000, "compactAt": 167_000}


def test_compacting_a_claude_thread_on_request_sends_the_compact_command(claude_thread):
    FakeClient.replies = [[_result()], [*_compacted("manual")[2:], _result(0.3)]]
    run = _start("first")
    _wait_for(lambda: run.state["summary"]["status"] == "done")

    run.compact()
    _wait_for(lambda: len(FakeClient.sessions) == 2 and not run._busy)
    assert FakeClient.sessions[1].resume == FakeClient.sessions[0].session_id
    assert FakeClient.prompts[-1] == [{"type": "text", "text": "/compact"}]
    [compacted] = run.state["compactions"]
    assert compacted["trigger"] == "manual" and compacted["status"] == "done"
    assert run.state["summary"]["status"] == "done" and run.state["summary"]["cost"]["usd"] == pytest.approx(0.3)


def test_a_thread_without_a_session_has_nothing_to_compact(claude_thread):
    from ov.agent.engine.run import RunError

    FakeClient.replies = [[_result()]]
    run = _start("first")
    _wait_for(lambda: run.state["summary"]["status"] == "done")
    run.state["claude"]["session"] = None
    with pytest.raises(RunError, match="nothing to compact"):
        run.compact()


def test_the_model_window_leaves_claude_code_to_pick_when_to_compact(claude_thread):
    FakeClient.replies = [[_result()]]
    run = _start("first")
    _wait_for(lambda: run.state["summary"]["status"] == "done")
    assert FakeClient.sessions[0].env == {}
