from __future__ import annotations

import threading
import time

import httpx
from helpers.agent import RUN_POLL_SECONDS, wait_done
from sqlalchemy import update

from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db, models
from ov.agent.storage.models import Access

STOP_SECONDS = 5
JSON_HEADERS = {"Content-Type": "application/json"}


def test_a_run_can_be_renamed(agent_server, monkeypatch):
    from ov.agent.engine.run_manager import runs

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    run = runs.create({"access": "read", "prompt": "x"}, "copilot", "m")
    ok = httpx.post(f"{agent_server}/api/threads/{run.id}/title", json={"title": "  NORAD   report "})
    assert ok.status_code == 200
    assert db.list_threads()[0]["title"] == "NORAD report"

    blank = httpx.post(f"{agent_server}/api/threads/{run.id}/title", json={"title": " "})
    assert blank.status_code == 400


def test_a_thread_exports_as_markdown(agent_server, monkeypatch):
    replies = iter(
        [
            StreamResult(
                text="Checking the tags.",
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "ov", "arguments": '{"args": ["api", "tags"]}'},
                    }
                ],
            ),
            StreamResult(text="There are **3** tags."),
        ]
    )

    def fake_chat(*args, cancel, on_text, **_):
        reply = next(replies)
        on_text(reply.text)
        return reply

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(0, "ok\n", ""))

    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": "what tags?", "instance": "acme"}, "copilot", "test-model")
    wait_done(run)
    run.rename("Tags: on acme?")

    res = httpx.get(f"{agent_server}/api/threads/{run.id}/export")
    assert res.status_code == 200
    assert res.headers["content-disposition"] == "attachment; filename*=UTF-8''Tags%20on%20acme.md"
    text = res.text
    assert text.startswith("# Tags: on acme?\n\nModel: test-model (copilot) | Instance: acme")
    assert "Cost: not tracked" in text
    assert "\n## You, " in text and "\nwhat tags?\n" in text
    assert "\n## Agent\n\nChecking the tags.\n\n- " in text
    assert "(ok, " in text
    assert text.rstrip().endswith("There are **3** tags.")

    db.add_usage(run.id, "copilot", "test-model", "turn", tokens={"input": 10}, nano=1_500_000_000)
    assert "Cost: 1.50 credits" in httpx.get(f"{agent_server}/api/threads/{run.id}/export").text


def test_cost_routes_answer(agent_server):
    assert httpx.get(f"{agent_server}/api/cost?range=7d").json()["requests"] == 0
    assert httpx.get(f"{agent_server}/api/cost?range=year").status_code == 400
    assert httpx.get(f"{agent_server}/api/threads/rmissing/cost").status_code == 404


def test_pinned_and_snoozed_threads(agent_server):
    db.create_thread("rpin", "Pinned", "copilot", "m", instance=None, access=Access.READ)
    db.create_thread("rnap", "Napping", "copilot", "m", instance=None, access=Access.READ)
    assert (
        httpx.post(f"{agent_server}/api/threads/rpin/pin", json={"pinned": True}, headers=JSON_HEADERS).status_code
        == 200
    )
    later = db.now_ms() + 3_600_000
    assert (
        httpx.post(f"{agent_server}/api/threads/rnap/snooze", json={"until": later}, headers=JSON_HEADERS).status_code
        == 200
    )
    assert (
        httpx.post(f"{agent_server}/api/threads/rnap/snooze", json={"until": 5}, headers=JSON_HEADERS).status_code
        == 400
    )

    listed = httpx.get(f"{agent_server}/api/threads").json()
    assert [r["id"] for r in listed["active"]] == ["rpin"] and listed["active"][0]["pinned"]
    assert listed["snoozed"][0]["snoozedUntil"] == later

    with db._begin() as conn:
        conn.execute(update(models.Thread).where(models.Thread.id == "rnap").values(snoozed_until=db.now_ms() - 1))

    assert {r["id"] for r in httpx.get(f"{agent_server}/api/threads").json()["active"]} == {"rpin", "rnap"}


def test_deleting_a_thread_removes_everything_it_owns(agent_server):
    db.create_thread("rdel", "Gone", "copilot", "m", instance=None, access=Access.READ)
    db.append_event("rdel", 0, {"type": "status", "status": "done"})
    db.save_messages("rdel", 0, [{"role": "user", "content": "x"}], {0: "u_start"})
    db.add_usage("rdel", "copilot", "m", "turn", tokens={"input": 1}, nano=5)
    from ov.agent.engine.files import run_dir

    (run_dir("rdel") / "note.txt").write_text("x", encoding="utf-8")

    assert httpx.delete(f"{agent_server}/api/threads/rdel").status_code == 200
    assert db.get_thread("rdel") is None and db.load_events("rdel") == []
    assert db.load_messages("rdel") == ([], {}) and db.thread_cost("rdel")["requests"] == 0
    assert not run_dir("rdel").exists() or not any(run_dir("rdel").iterdir())


def _working_thread(monkeypatch):
    from ov.agent.engine.run_manager import runs

    started = threading.Event()

    def endless_chat(*_, cancel, on_text, **__):
        on_text("Looking")
        started.set()
        cancel.wait(STOP_SECONDS * 4)
        cancel.check()
        return StreamResult(text="never")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", endless_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    run = runs.create({"access": "read", "prompt": "hi"}, "copilot", "test-model")
    assert started.wait(STOP_SECONDS)
    return run


def _until(check) -> bool:
    deadline = time.monotonic() + STOP_SECONDS
    while not check():
        if time.monotonic() > deadline:
            return False
        time.sleep(RUN_POLL_SECONDS)
    return True


def test_stop_really_stops_a_working_thread(logged_in, monkeypatch):
    run = _working_thread(monkeypatch)
    run.stop()
    assert _until(lambda: not run.working())
    assert run.state["summary"]["status"] == "cancelled"
    assert db.get_thread(run.id)["status"] == "cancelled"


def test_an_open_working_thread_is_stopped_and_deleted(logged_in, agent_server, monkeypatch):
    from ov.agent.engine.run import STREAM_END

    run = _working_thread(monkeypatch)
    channel, unsubscribe, _ = run.resume(-1)

    assert httpx.delete(f"{agent_server}/api/threads/{run.id}").status_code == 200

    assert not run.working()
    assert db.get_thread(run.id) is None and db.load_events(run.id) == []

    seen = []
    while True:
        item = channel.get(timeout=STOP_SECONDS)
        if item is STREAM_END:
            break
        seen.append(item)

    assert any(s["event"].get("status") == "cancelled" for s in seen)
    assert httpx.get(f"{agent_server}/api/threads/{run.id}").status_code == 404
    unsubscribe()


def test_snooze_and_settle_wait_for_an_answer_and_a_waiting_thread_wakes(agent_server):
    from ov.agent.engine.run_manager import runs

    db.create_thread("rwake", "Wake", "copilot", "m", instance=None, access=Access.READ)
    later = db.now_ms() + 3_600_000
    db.set_snoozed("rwake", later)
    db.set_settled("rwake", True)
    run = runs.get("rwake")

    run.emit({"type": "status", "status": "waiting"})

    thread = db.get_thread("rwake")
    assert "snoozedUntil" not in thread and "settled" not in thread
    snoozed = httpx.post(f"{agent_server}/api/threads/rwake/snooze", json={"until": later}, headers=JSON_HEADERS)
    settled = httpx.post(f"{agent_server}/api/threads/rwake/settle", json={"settled": True}, headers=JSON_HEADERS)
    assert snoozed.status_code == 400 and "waiting for you" in snoozed.json()["error"]
    assert settled.status_code == 400

    run.emit({"type": "status", "status": "running"})
    assert (
        httpx.post(f"{agent_server}/api/threads/rwake/snooze", json={"until": later}, headers=JSON_HEADERS).status_code
        == 200
    )
    run.emit({"type": "status", "status": "done"})
    assert "snoozedUntil" not in db.get_thread("rwake")


def test_a_new_turn_brings_a_settled_or_snoozed_thread_back(agent_server):
    from ov.agent.engine.run_manager import runs

    db.create_thread("rback", "Back", "copilot", "m", instance=None, access=Access.READ)
    db.set_snoozed("rback", db.now_ms() + 3_600_000)
    db.set_settled("rback", True)

    runs.get("rback").emit({"type": "status", "status": "running"})

    thread = db.get_thread("rback")
    assert "snoozedUntil" not in thread and "settled" not in thread


def test_tool_routes_refuse_a_tool_that_is_not_running(agent_server, monkeypatch):
    from ov.agent.engine.run_manager import runs

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    run = runs.create({"access": "read", "prompt": "x"}, "copilot", "m")
    for action in ("background", "stop"):
        response = httpx.post(f"{agent_server}/api/threads/{run.id}/tools/call_x1/{action}", json={})
        assert response.status_code == 400
        assert "no longer running" in response.json()["error"]


def test_input_for_a_closed_sign_in_screen_is_not_an_error(agent_server):
    url = f"{agent_server}/api/signin/input?url=https://acme.example&tenant="
    response = httpx.post(url, json={"events": [{"type": "back"}]})
    assert response.status_code == 200 and response.json() == {"open": False}


def _finished_thread(agent_server, monkeypatch, reply: str) -> str:
    monkeypatch.setattr(
        "ov.agent.integrations.copilot.stream_chat",
        lambda *a, on_text, **k: (on_text(reply), StreamResult(text=reply))[1],
    )
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)
    from ov.agent.engine.run_manager import runs

    run = runs.create({"access": "read", "prompt": "which tags on acme?", "instance": "acme"}, "copilot", "m")
    wait_done(run)
    return run.id


def test_branch_routes_make_a_branch_and_list_it_under_its_parent(agent_server, monkeypatch):
    parent = _finished_thread(agent_server, monkeypatch, "Tags A and B.")

    made = httpx.post(f"{agent_server}/api/threads/{parent}/branch", json={})
    assert made.status_code == 200
    branch = made.json()["id"]

    listed = httpx.get(f"{agent_server}/api/threads/{parent}/branches").json()["branches"]
    assert [(b["id"], b["parentId"], b["origin"]) for b in listed] == [(branch, parent, "branch")]
    snapshot = httpx.get(f"{agent_server}/api/threads/{branch}").json()
    assert snapshot["parent"]["id"] == parent and snapshot["inheritedItems"] == len(snapshot["items"])

    wrong = httpx.post(f"{agent_server}/api/threads/{parent}/branch", json={"before": "u_nope"})
    assert wrong.status_code == 400 and "does not start a turn" in wrong.json()["error"]


def test_finding_routes_add_edit_and_remove(agent_server, monkeypatch):
    thread = _finished_thread(agent_server, monkeypatch, "Tags A and B.")
    base = f"{agent_server}/api/threads/{thread}/findings"

    added = httpx.post(base, json={"text": "acme has tags A and B"}).json()
    assert httpx.post(f"{base}/{added['id']}", json={"text": "acme has tags A, B"}).status_code == 200
    assert [f["text"] for f in httpx.get(base).json()["findings"]] == ["acme has tags A, B"]
    assert httpx.delete(f"{base}/{added['id']}").status_code == 200
    assert httpx.get(base).json()["findings"] == []
    assert httpx.delete(f"{base}/{added['id']}").status_code == 400


def test_search_route_finds_threads_by_message_text(agent_server, monkeypatch):
    thread = _finished_thread(agent_server, monkeypatch, "The kafka consumer lags.")

    found = httpx.get(f"{agent_server}/api/search", params={"q": "consumer lags"}).json()["threads"]
    assert [t["id"] for t in found] == [thread]
    assert httpx.get(f"{agent_server}/api/search", params={"q": "ab"}).status_code == 400
