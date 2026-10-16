from __future__ import annotations

import time

import pytest

from ov.agent.integrations.copilot import StreamResult, Usage
from ov.agent.storage import db
from ov.agent.storage.models import Provider


def test_titles_are_cleaned_and_kept_short():
    from ov.agent.engine.run import TITLE_CHARS, clean_title, short_title

    assert clean_title('Title: "Kafka staging backlog on dev-lumen."\nmore') == "Kafka staging backlog on dev-lumen"
    assert clean_title("**Rule queue**") == "Rule queue"
    long = clean_title(" ".join(f"word{i}" for i in range(40)))
    assert len(long.split()) == 8
    sentence = "x" * 10 + " " + "y" * 200
    assert len(short_title(sentence, TITLE_CHARS)) <= TITLE_CHARS
    assert (
        short_title("Investigate why the import keeps failing on production every night", 30)
        == "Investigate why the import"
    )


def test_a_fast_model_names_the_run(logged_in, monkeypatch):
    db.save_preferences({"fastModel": "fast-model"})
    seen: list[str] = []

    def fake_chat(*args, cancel, on_text, **_):
        return StreamResult(text="Done.")

    def fake_complete(model, system, user_text, max_tokens=200):
        seen.append(model)
        return '"Tag listing question."', Usage(tokens={"input": 50, "output": 4}, nano=30_000_000)

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.complete", fake_complete)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    from ov.agent.engine.run import runs

    run = runs.create(
        {"access": "read", "prompt": "what tags are there on this instance?", "instance": "acme"},
        Provider.COPILOT,
        "main-model",
    )
    for _ in range(100):
        if run.state["summary"]["title"] == "Tag listing question":
            break
        time.sleep(0.05)

    assert run.state["summary"]["title"] == "Tag listing question"
    assert seen == ["fast-model"]
    assert db.thread_cost(run.id)["models"][0] == {
        "model": "fast-model",
        "provider": "copilot",
        "credits": 0.03,
        "usd": 0.0,
        "requests": 1,
    }


def test_a_copilot_thread_needs_a_fast_model(logged_in, monkeypatch):
    from ov.agent.engine.run import NO_FAST_MODEL, RunError, runs

    db.save_preferences({"fastModel": ""})
    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    run = runs.create(
        {"access": "read", "prompt": "why is the queue long?", "instance": "acme"}, Provider.COPILOT, "main-model"
    )
    with pytest.raises(RunError, match=NO_FAST_MODEL):
        run.retitle()


def test_only_the_preloaded_case_names_the_thread(logged_in, monkeypatch):
    from ov.agent.engine.run import runs
    from ov.agent.storage.models import Access

    bundles = {
        ref: {"key": ref, "title": f"Case {ref} title", "url": f"https://t/{ref}", "website": "acme"}
        for ref in ("C1", "C2")
    }
    monkeypatch.setattr("ov.agent.engine.cases.load_case", lambda ref, work_dir, cancel: bundles[ref])
    monkeypatch.setattr("ov.agent.engine.cases.render", lambda bundle, work_dir: bundle["title"])
    db.create_thread("rcase", "Kafka sync", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    run = runs.get("rcase")

    run.read_case("C1", run.cancel)
    run.read_case("C2", run.cancel)
    assert run.state["summary"]["title"] == "Kafka sync" and run.state["summary"]["caseKey"] == "C1"
