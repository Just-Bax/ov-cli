from __future__ import annotations

from helpers.agent import wait_done

from ov.agent.integrations.copilot import StreamResult, Usage


def test_a_bare_case_number_or_link_is_a_case():
    from ov.agent.engine.cases import case_ref

    assert case_ref("193915") == "193915"
    assert case_ref(" Case #193915 ") == "193915"
    link = "https://trackor.onevizion.com/form/ConfigAppForm.do?id=100124829949"
    assert case_ref(link) == link
    assert case_ref("why does case 193915 fail?") is None


def test_a_case_reply_is_drafted_with_the_reply_style(logged_in, monkeypatch):
    calls: list[tuple] = []

    def fake_complete(model, system, user_text, max_tokens=200):
        calls.append((model, system, user_text, max_tokens))
        return "Fixed.\n\nI've updated the rule.", Usage(tokens={"output": 10}, nano=100_000_000)

    monkeypatch.setattr("ov.agent.integrations.copilot.complete", fake_complete)

    def fake_chat(*args, cancel, on_text, **_):
        on_text("Found it.")
        return StreamResult(text="Found it.")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create({"prompt": "case 1234: rule fails", "instance": "acme"}, "test-model")
    wait_done(run)
    answer = next(m for m in run.state["chat"] if m["role"] == "assistant")
    assert run.draft_reply(answer["id"]).startswith("Fixed.")
    model, system, user_text, max_tokens = calls[-1]
    assert model == "test-model" and "## Reply style" in system and "Write as I, never we" in system
    assert "Found it." in user_text and "case 1234" in user_text and max_tokens > 200
