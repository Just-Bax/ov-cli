from __future__ import annotations

import copy

import pytest
from helpers.agent import wait_done, wait_for

from ov.agent.engine import compaction
from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult, Usage
from ov.agent.providers.base import ContextLimits
from ov.agent.storage import db

WINDOW = 264_000
PROMPT_LIMIT = 200_000
OUTPUT_LIMIT = 64_000
FULL_CONTEXT = Usage(tokens={"input": 2, "cache_read": 190_000, "output": 50}, nano=0)
SUMMARY = "The user asked about tags. The agent listed them."
CALL = {"id": "c1", "type": "function", "function": {"name": "ov", "arguments": '{"args": ["api", "tags"]}'}}


def _history() -> list[dict]:
    return [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "check the tags"},
        {"role": "assistant", "content": "Looking.", "tool_calls": [CALL]},
        {"role": "tool", "tool_call_id": "c1", "content": "x" * 4000},
        {"role": "assistant", "content": "Found them."},
        {"role": "user", "content": [{"type": "text", "text": "and this"}, {"type": "image_url", "image_url": {}}]},
        {"role": "assistant", "content": None, "tool_calls": [CALL]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]


def test_the_cut_keeps_a_recent_tail_that_starts_at_a_whole_step():
    history = _history()
    assert compaction.cut_point(history, keep_tokens=compaction.estimate_tokens(history[5:])) == 5
    assert compaction.cut_point(history, keep_tokens=10) == 6
    assert compaction.cut_point(history[:2], keep_tokens=10) is None


def test_the_transcript_names_tool_calls_and_leaves_images_out():
    text = compaction.transcript(_history()[1:6])
    assert "User:\ncheck the tags" in text and 'Agent called ov({"args": ["api", "tags"]})' in text
    assert "[image]" in text and "image_url" not in text
    assert len(text) < compaction.TRANSCRIPT_TOOL_CHARS + 500


def test_the_summary_replaces_everything_before_the_cut():
    history = _history()
    rebuilt = compaction.rebuilt(history, 5, SUMMARY)
    assert rebuilt[0] == history[0] and rebuilt[2:] == history[5:]
    assert rebuilt[1] == {"role": "user", "content": compaction.SUMMARY_HEADER + SUMMARY}


def test_the_compact_point_follows_the_claude_code_rule():
    assert ContextLimits(window=1_000_000, prompt=1_000_000, output=64_000).compact_at == 967_000
    assert ContextLimits(window=WINDOW, prompt=PROMPT_LIMIT, output=OUTPUT_LIMIT).compact_at == 187_000
    assert ContextLimits(window=400_000, prompt=272_000, output=128_000).compact_at == 259_000


@pytest.fixture
def copilot_thread(logged_in, monkeypatch):
    sent: list[list[dict]] = []
    summarized: list[str] = []
    replies = iter(
        [
            StreamResult(text="Checking.", tool_calls=[CALL], usage=FULL_CONTEXT),
            StreamResult(text="All good.", usage=FULL_CONTEXT),
        ]
    )

    def stream(model, messages, *a, cancel, on_text, **_):
        sent.append(copy.deepcopy(messages))
        return next(replies)

    def complete(model, system, text, *a):
        summarized.append(text)
        return SUMMARY, None

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", stream)
    monkeypatch.setattr("ov.agent.integrations.copilot.complete", complete)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    monkeypatch.setattr("ov.agent.integrations.copilot.token_limits", lambda _: (WINDOW, PROMPT_LIMIT, OUTPUT_LIMIT))
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(0, "users\n", ""))
    return sent, summarized


def _start():
    from ov.agent.engine.run import runs

    return runs.create({"access": "read", "prompt": "what tags?", "instance": "acme"}, "copilot", "test-model")


def test_a_full_copilot_context_is_summarized_before_the_next_step(copilot_thread):
    sent, summarized = copilot_thread
    run = _start()
    wait_done(run)

    assert "what tags?" in summarized[0]
    second = sent[1]
    assert second[1]["content"] == compaction.SUMMARY_HEADER + SUMMARY
    assert second[2]["tool_calls"][0]["id"] == "c1" and second[3]["role"] == "tool"
    [compacted] = run.state["compactions"]
    assert compacted["trigger"] == "auto" and compacted["status"] == "done"
    assert compacted["before"] == 190_052 and compacted["after"] < FULL_CONTEXT.tokens["cache_read"] // 10
    assert db.thread_cost(run.id)["requests"] == 2


def test_compacting_a_copilot_thread_on_request_summarizes_it(copilot_thread, monkeypatch):
    roomy = ContextLimits(window=WINDOW * 2, prompt=PROMPT_LIMIT * 2, output=OUTPUT_LIMIT)
    monkeypatch.setattr("ov.agent.providers.copilot_turn.limits", lambda model: roomy)
    run = _start()
    wait_done(run)
    assert not run.state["compactions"]

    run.compact()
    wait_for(lambda: run.state["compactions"] and not run._busy)

    [compacted] = run.state["compactions"]
    assert compacted["trigger"] == "manual" and compacted["status"] == "done"
    assert run.messages[1]["content"].endswith(SUMMARY) and run.state["summary"]["status"] == "done"
