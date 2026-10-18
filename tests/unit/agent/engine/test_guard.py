from __future__ import annotations

import pytest

from ov.agent.engine.guard import COMMAND_EFFECTS, PAGE_EFFECTS, Effect, GuardError, Verdict, parse
from ov.agent.integrations.copilot import StreamResult, Usage
from ov.agent.storage.models import Provider


def test_a_judgement_is_read_from_the_model_reply():
    assert parse('{"effect": "outside", "reason": "pushes to a remote"}', "m", COMMAND_EFFECTS) == Verdict(
        Effect.OUTSIDE, "pushes to a remote"
    )
    assert parse('Sure:\n{"effect": "READ", "reason": " lists  files "}', "m", COMMAND_EFFECTS) == Verdict(
        Effect.READ, "lists files"
    )


def test_a_page_action_is_judged_read_or_write_only():
    assert parse('{"effect": "write", "reason": "saves the form"}', "m", PAGE_EFFECTS) == Verdict(
        Effect.WRITE, "saves the form"
    )
    with pytest.raises(GuardError):
        parse('{"effect": "outside", "reason": "x"}', "m", PAGE_EFFECTS)


@pytest.mark.parametrize(
    "reply",
    ["no json here", '{"effect": "maybe", "reason": "x"}', '{"effect": "read"}', '{"effect": "read", "reason": '],
)
def test_an_unusable_judgement_stops_the_command(reply):
    with pytest.raises(GuardError):
        parse(reply, "m", COMMAND_EFFECTS)


def test_the_run_judges_each_command_once_and_records_it(logged_in, monkeypatch):
    calls: list[str] = []

    def fake_complete(model, system, user_text, max_tokens=200):
        calls.append(user_text)
        return '{"effect": "change", "reason": "writes build output"}', Usage(tokens={"output": 5}, nano=1)

    monkeypatch.setattr("ov.agent.integrations.copilot.complete", fake_complete)
    monkeypatch.setattr(
        "ov.agent.integrations.copilot.stream_chat", lambda *a, cancel, on_text, **_: StreamResult(text="ok")
    )
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from helpers.agent import wait_done

    from ov.agent.engine.run import runs
    from ov.agent.storage import db

    run = runs.create({"access": "read", "prompt": "hi", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)

    run.emit({"type": "tool", "tool": {"id": "t1", "name": "ws_run", "label": "$ mvn", "status": "running"}})
    run._local.tool = "t1"

    first = run.judge_command("mvn package", "module")
    again = run.judge_command("mvn package", "module")
    assert first == again == Verdict(Effect.CHANGE, "writes build output")
    assert len([c for c in calls if "<command>" in c]) == 1
    assert "<folder>module</folder>" in calls[-1]

    tool = next(t for t in run.state["tools"] if t["id"] == "t1")
    assert tool["verdict"] == {"effect": "change", "reason": "writes build output"}

    with db._begin() as conn:
        kinds = {row[0] for row in conn.exec_driver_sql("select kind from usage").all()}
    assert "guard" in kinds
