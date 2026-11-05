from __future__ import annotations

import copy

import pytest
from helpers.agent import TEST_TITLE_REPLY, is_title_prompt, new_message_id, wait_done, wait_for

from ov.agent.engine.files import run_dir
from ov.agent.engine.run_branch import BRING_BACK_PROMPT
from ov.agent.engine.run_common import RunError
from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db

NOTE = "- The tags are A and B on acme."


class FakeModel(list):
    def __init__(self) -> None:
        super().__init__()
        self.notes: list[str] = []


def _chat(monkeypatch, *texts: str) -> FakeModel:
    sent = FakeModel()
    replies = iter(texts)

    def stream(model, messages, *a, cancel, on_text, **_):
        sent.append(copy.deepcopy(messages))
        text = next(replies)
        on_text(text)
        return StreamResult(text=text)

    def complete(model, system, text, *a):
        if is_title_prompt(system):
            return '{"title": "Tag check"}', None
        if system == BRING_BACK_PROMPT:
            sent.notes.append(text)
            return NOTE, None
        return TEST_TITLE_REPLY, None

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", stream)
    monkeypatch.setattr("ov.agent.integrations.copilot.complete", complete)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    return sent


def _thread(*turns: str):
    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": turns[0], "instance": "acme"}, "copilot", "test-model")
    wait_done(run)
    for text in turns[1:]:
        run.follow_up(new_message_id(), text, [], False)
        wait_done(run)
    return run


def _texts(messages: list[dict]) -> list[str]:
    return [m["content"] if isinstance(m["content"], str) else m["content"][0]["text"] for m in messages[1:]]


def test_a_branch_starts_with_the_exact_context_and_leaves_the_parent_alone(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    sent = _chat(monkeypatch, "A and B.", "Only A is used.")
    parent = _thread("which tags?")
    parent_items = len(parent.state["items"])

    branch = runs.branch(parent.id)
    assert branch.state["summary"]["title"] == f"{parent.state['summary']['title']} (branch)"
    assert (branch.state["summary"]["parentId"], branch.state["summary"]["origin"]) == (parent.id, "branch")
    assert branch.state["parent"] == {"id": parent.id, "title": parent.state["summary"]["title"]}
    assert branch.state["inheritedItems"] == parent_items
    assert branch.state["summary"]["originTurnId"] == "u_start"
    assert (branch.provider, branch.model, branch.instance, branch.access) == (
        parent.provider,
        parent.model,
        parent.instance,
        parent.access,
    )
    assert [m["role"] for m in branch.messages] == [m["role"] for m in parent.messages]

    branch.follow_up(new_message_id(), "which one is used?", [], False)
    wait_done(branch)

    assert _texts(sent[-1])[:2] == [*_texts(sent[0])[:1], "A and B."]
    assert branch.state["summary"]["title"] == "Tag check"
    assert len(parent.state["items"]) == parent_items
    assert [t["id"] for t in db.child_threads(parent.id)] == [branch.id]


def test_an_aside_is_a_branch_with_its_first_message(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    sent = _chat(monkeypatch, "A and B.", "B came from the import.")
    parent = _thread("which tags?")

    aside = runs.aside(parent.id, new_message_id(), "where did B come from?", [])
    wait_done(aside)

    assert _texts(sent[-1])[-1].endswith("where did B come from?")
    assert aside.state["chat"][-1]["text"] == "B came from the import."
    assert all(m["text"] != "where did B come from?" for m in parent.state["chat"])


def test_retry_as_branch_keeps_the_original_and_reruns_the_message_in_the_branch(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    sent = _chat(monkeypatch, "A and B.", "First answer.", "Second answer.")
    parent = _thread("which tags?", "and which is used?")
    second = parent.state["chat"][-2]["id"]

    branch = runs.retry_as_branch(parent.id, second)
    wait_done(branch)

    assert _texts(sent[-1]) == [_texts(sent[0])[0], "A and B.", _texts(sent[1])[-1]]
    assert branch.state["chat"][-1]["text"] == "Second answer."
    assert parent.state["chat"][-1]["text"] == "First answer."
    assert branch.state["summary"]["originTurnId"] == "u_start"


def test_inherited_messages_and_data_changes_cannot_be_redone_in_the_branch(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    _chat(monkeypatch, "A and B.")
    parent = _thread("which tags?")
    (run_dir(parent.id) / "grid_1.change.json").write_text("{}", encoding="utf-8")
    (run_dir(parent.id) / "notes.txt").write_text("kept", encoding="utf-8")
    parent.emit({"type": "grid", "grid": {"id": "grid_1", "title": "Tags", "change": {"state": "done", "updated": 1}}})

    branch = runs.branch(parent.id)

    with pytest.raises(RunError, match="came from the thread this one branched from"):
        branch.retry("u_start")
    with pytest.raises(RunError, match="Revert it there"):
        branch.revert_grid("grid_1")
    assert (run_dir(branch.id) / "notes.txt").read_text(encoding="utf-8") == "kept"
    assert not (run_dir(branch.id) / "grid_1.change.json").exists()


def test_a_busy_thread_branches_from_its_last_finished_turn(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    _chat(monkeypatch, "A and B.")
    parent = _thread("which tags?")
    finished = len(parent.state["items"])

    parent._busy = True
    parent.emit({"type": "user_message", "message": {"id": "u_live", "role": "user", "text": "more", "ts": 1}})
    try:
        branch = runs.branch(parent.id)
    finally:
        parent._busy = False

    assert branch.state["inheritedItems"] == finished
    assert all(m["id"] != "u_live" for m in branch.state["chat"])


def test_a_branch_brings_back_only_its_own_work_to_the_parent(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    sent = _chat(monkeypatch, "A and B.", "Only A is used.", "Noted.")
    parent = _thread("which tags?")
    branch = runs.aside(parent.id, new_message_id(), "which one is used?", [])
    wait_done(branch)

    draft = branch.bring_back_draft()
    assert draft == NOTE
    assert "which one is used?" in sent.notes[-1] and "which tags?" not in sent.notes[-1]

    runs.bring_back(branch.id, draft)
    (result,) = parent.state["branchResults"]
    assert result["branch"] == {"id": branch.id, "title": branch.state["summary"]["title"]}
    assert {"kind": "branch_result", "id": result["id"]} in parent.state["items"]

    parent.follow_up(new_message_id(), "so what now?", [], False)
    wait_done(parent)
    assert NOTE in _texts(sent[-1])[-2] and _texts(sent[-1])[-1].endswith("so what now?")


def test_bringing_back_waits_for_a_busy_parent(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    _chat(monkeypatch, "A and B.")
    parent = _thread("which tags?")
    branch = runs.branch(parent.id)

    parent._busy = True
    try:
        with pytest.raises(RunError, match="Wait for the parent thread"):
            runs.bring_back(branch.id, NOTE)
    finally:
        parent._busy = False


def test_findings_follow_branches_and_start_new_threads(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    _chat(monkeypatch, "A and B.", "Checked.")
    parent = _thread("which tags?")
    parent.save_finding("acme has tags A and B")
    branch = runs.branch(parent.id)
    parent.follow_up(new_message_id(), "check the import", [], False)
    wait_done(parent)
    parent.save_finding("the import adds tag B")

    assert [f["text"] for f in db.list_findings(branch.id)] == ["acme has tags A and B"]

    fresh = runs.from_findings(parent.id)
    wait_done(fresh)
    assert fresh.state["summary"]["origin"] == "findings"
    assert [f["text"] for f in db.list_findings(fresh.id)] == ["acme has tags A and B", "the import adds tag B"]
    assert "- the import adds tag B" in fresh.messages[1]["content"]
    assert fresh.state["chat"][-1]["text"].startswith("Started from the findings of")

    with pytest.raises(RunError, match="needs some text"):
        parent.save_finding("  ")


def test_a_thread_without_findings_cannot_start_one_from_them(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    _chat(monkeypatch, "A and B.")
    parent = _thread("which tags?")

    with pytest.raises(RunError, match="no findings yet"):
        runs.from_findings(parent.id)


def test_deleting_the_parent_keeps_its_branches(logged_in, monkeypatch):
    from ov.agent.engine.run_manager import runs

    _chat(monkeypatch, "A and B.")
    parent = _thread("which tags?")
    branch = runs.branch(parent.id)

    runs.delete(parent.id)
    runs._runs.pop(branch.id)

    kept = runs.get(branch.id)
    assert "parentId" not in kept.state["summary"] and kept.state["parent"] is None
    assert kept.state["summary"]["origin"] == "branch" and kept.state["inheritedItems"] > 0


def test_threads_are_found_by_title_and_message_text(logged_in, monkeypatch):
    _chat(monkeypatch, "The rule 50% filter is slow.", "Fine.")
    slow = _thread("why is the kafka rule slow?")
    _thread("unrelated")
    wait_for(lambda: slow.state["summary"]["title"] == "Tag check")

    found = db.search_threads("50% filter")
    assert [t["id"] for t in found] == [slow.id]
    assert "50% filter" in found[0]["snippet"]
    assert db.search_threads("5_% filter") == []

    from ov.agent.engine.run_manager import runs

    runs.branch(slow.id)
    assert [t["id"] for t in db.search_threads("50% filter")] == [slow.id]
    assert [t["id"] for t in db.search_threads("tag check")][:2] != []
