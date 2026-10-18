from __future__ import annotations

import threading
import time

import httpx
from helpers.agent import RUN_POLL_SECONDS, wait_done
from sqlalchemy import update

from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db, models
from ov.agent.storage.models import Access, Provider

STOP_SECONDS = 5
JSON_HEADERS = {"Content-Type": "application/json"}


def test_a_run_can_be_renamed(agent_server, monkeypatch):
    from ov.agent.engine.run import runs

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    run = runs.create({"access": "read", "prompt": "x"}, Provider.COPILOT, "m")
    ok = httpx.post(f"{agent_server}/api/runs/{run.id}/title", json={"title": "  NORAD   report "})
    assert ok.status_code == 200
    assert db.list_threads()[0]["title"] == "NORAD report"

    blank = httpx.post(f"{agent_server}/api/runs/{run.id}/title", json={"title": " "})
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

    from ov.agent.engine.run import runs

    run = runs.create({"access": "read", "prompt": "what tags?", "instance": "acme"}, Provider.COPILOT, "test-model")
    wait_done(run)
    run.rename("Tags: on acme?")

    res = httpx.get(f"{agent_server}/api/runs/{run.id}/export")
    assert res.status_code == 200
    assert res.headers["content-disposition"] == "attachment; filename*=UTF-8''Tags%20on%20acme.md"
    text = res.text
    assert text.startswith("# Tags: on acme?\n\nModel: test-model (copilot) | Instance: acme")
    assert "Cost: not tracked" in text
    assert "\n## You, " in text and "\nwhat tags?\n" in text
    assert "\n## Agent\n\nChecking the tags.\n\n- " in text
    assert "(ok, " in text
    assert text.rstrip().endswith("There are **3** tags.")


def test_cost_routes_answer(agent_server):
    assert httpx.get(f"{agent_server}/api/cost?range=7d").json()["requests"] == 0
    assert httpx.get(f"{agent_server}/api/cost?range=year").status_code == 400
    assert httpx.get(f"{agent_server}/api/runs/rmissing/cost").status_code == 404


def test_pinned_and_snoozed_threads(agent_server):
    db.create_thread("rpin", "Pinned", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    db.create_thread("rnap", "Napping", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    assert (
        httpx.post(f"{agent_server}/api/runs/rpin/pin", json={"pinned": True}, headers=JSON_HEADERS).status_code == 200
    )
    later = db.now_ms() + 3_600_000
    assert (
        httpx.post(f"{agent_server}/api/runs/rnap/snooze", json={"until": later}, headers=JSON_HEADERS).status_code
        == 200
    )
    assert (
        httpx.post(f"{agent_server}/api/runs/rnap/snooze", json={"until": 5}, headers=JSON_HEADERS).status_code == 400
    )

    listed = httpx.get(f"{agent_server}/api/runs").json()
    assert [r["id"] for r in listed["active"]] == ["rpin"] and listed["active"][0]["pinned"]
    assert listed["snoozed"][0]["snoozedUntil"] == later

    with db._begin() as conn:
        conn.execute(update(models.Thread).where(models.Thread.id == "rnap").values(snoozed_until=db.now_ms() - 1))

    assert {r["id"] for r in httpx.get(f"{agent_server}/api/runs").json()["active"]} == {"rpin", "rnap"}


def test_deleting_a_thread_removes_everything_it_owns(agent_server):
    db.create_thread("rdel", "Gone", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    db.append_event("rdel", 0, {"type": "status", "status": "done"})
    db.save_messages("rdel", 0, [{"role": "user", "content": "x"}], {0: "u_start"})
    db.add_usage("rdel", Provider.COPILOT, "m", "turn", tokens={"input": 1}, nano=5)
    db.add_attachments("rdel", "u_start", ["a.txt"])
    from ov.agent.engine.files import run_dir

    (run_dir("rdel") / "note.txt").write_text("x", encoding="utf-8")

    assert httpx.delete(f"{agent_server}/api/runs/rdel").status_code == 200
    assert db.get_thread("rdel") is None and db.load_events("rdel") == []
    assert db.load_messages("rdel") == ([], {}) and db.thread_cost("rdel")["requests"] == 0
    assert not run_dir("rdel").exists() or not any(run_dir("rdel").iterdir())


def _working_thread(monkeypatch):
    from ov.agent.engine.run import runs

    started = threading.Event()

    def endless_chat(*_, cancel, on_text, **__):
        on_text("Looking")
        started.set()
        cancel.wait(STOP_SECONDS * 4)
        cancel.check()
        return StreamResult(text="never")

    monkeypatch.setattr("ov.agent.integrations.copilot.stream_chat", endless_chat)
    monkeypatch.setattr("ov.agent.integrations.copilot.supports_vision", lambda _: True)

    run = runs.create({"access": "read", "prompt": "hi"}, Provider.COPILOT, "test-model")
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

    assert httpx.delete(f"{agent_server}/api/runs/{run.id}").status_code == 200

    assert not run.working()
    assert db.get_thread(run.id) is None and db.load_events(run.id) == []

    seen = []
    while True:
        item = channel.get(timeout=STOP_SECONDS)
        if item is STREAM_END:
            break
        seen.append(item)

    assert any(s["event"].get("status") == "cancelled" for s in seen)
    assert httpx.get(f"{agent_server}/api/runs/{run.id}").status_code == 404
    unsubscribe()


def test_snooze_and_settle_wait_for_an_answer_and_a_waiting_thread_wakes(agent_server):
    from ov.agent.engine.run import runs

    db.create_thread("rwake", "Wake", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    later = db.now_ms() + 3_600_000
    db.set_snoozed("rwake", later)
    db.set_settled("rwake", True)
    run = runs.get("rwake")

    run.emit({"type": "status", "status": "waiting"})

    thread = db.get_thread("rwake")
    assert "snoozedUntil" not in thread and "settled" not in thread
    snoozed = httpx.post(f"{agent_server}/api/runs/rwake/snooze", json={"until": later}, headers=JSON_HEADERS)
    settled = httpx.post(f"{agent_server}/api/runs/rwake/settle", json={"settled": True}, headers=JSON_HEADERS)
    assert snoozed.status_code == 400 and "waiting for you" in snoozed.json()["error"]
    assert settled.status_code == 400

    run.emit({"type": "status", "status": "running"})
    assert (
        httpx.post(f"{agent_server}/api/runs/rwake/snooze", json={"until": later}, headers=JSON_HEADERS).status_code
        == 200
    )
    run.emit({"type": "status", "status": "done"})
    assert "snoozedUntil" not in db.get_thread("rwake")


def test_tool_routes_refuse_a_tool_that_is_not_running(agent_server, monkeypatch):
    from ov.agent.engine.run import runs

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    run = runs.create({"access": "read", "prompt": "x"}, Provider.COPILOT, "m")
    for action in ("background", "stop"):
        response = httpx.post(f"{agent_server}/api/runs/{run.id}/tools/call_x1/{action}", json={})
        assert response.status_code == 400
        assert "no longer running" in response.json()["error"]


def test_input_for_a_closed_sign_in_screen_is_not_an_error(agent_server):
    url = f"{agent_server}/api/signin/input?url=https://acme.example&tenant="
    response = httpx.post(url, json={"events": [{"type": "back"}]})
    assert response.status_code == 200 and response.json() == {"open": False}
