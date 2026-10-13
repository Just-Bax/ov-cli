from __future__ import annotations

import httpx
from helpers.agent import wait_done
from sqlalchemy import update

from ov.agent.instances.ovproc import OvResult
from ov.agent.integrations.copilot import StreamResult
from ov.agent.storage import db, models


def test_a_run_can_be_renamed(agent_server, monkeypatch):
    from ov.agent.engine.run import runs

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    run = runs.create({"prompt": "x"}, "m")
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

    run = runs.create({"prompt": "what tags?", "instance": "acme"}, "test-model")
    wait_done(run)
    run.rename("Tags: on acme?")

    res = httpx.get(f"{agent_server}/api/runs/{run.id}/export")
    assert res.status_code == 200
    assert res.headers["content-disposition"] == "attachment; filename*=UTF-8''Tags%20on%20acme.md"
    text = res.text
    assert text.startswith("# Tags: on acme?\n\nModel: test-model | Instance: acme")
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
    db.create_thread("rpin", "Pinned", "m", prompt="x", instance=None, allow_write=False)
    db.create_thread("rnap", "Napping", "m", prompt="x", instance=None, allow_write=False)
    J = {"Content-Type": "application/json"}
    assert httpx.post(f"{agent_server}/api/runs/rpin/pin", json={"pinned": True}, headers=J).status_code == 200
    later = db.now_ms() + 3_600_000
    assert httpx.post(f"{agent_server}/api/runs/rnap/snooze", json={"until": later}, headers=J).status_code == 200
    assert httpx.post(f"{agent_server}/api/runs/rnap/snooze", json={"until": 5}, headers=J).status_code == 400

    listed = httpx.get(f"{agent_server}/api/runs").json()
    assert [r["id"] for r in listed["active"]] == ["rpin"] and listed["active"][0]["pinned"]
    assert listed["snoozed"][0]["snoozedUntil"] == later

    with db._begin() as conn:
        conn.execute(update(models.Thread).where(models.Thread.id == "rnap").values(snoozed_until=db.now_ms() - 1))
    assert {r["id"] for r in httpx.get(f"{agent_server}/api/runs").json()["active"]} == {"rpin", "rnap"}


def test_deleting_a_thread_removes_everything_it_owns(agent_server):
    db.create_thread("rdel", "Gone", "m", prompt="x", instance=None, allow_write=False)
    db.append_event("rdel", 0, {"type": "status", "status": "done"})
    db.save_messages("rdel", 0, [{"role": "user", "content": "x"}], {0: "u_start"})
    db.add_usage("rdel", "m", "turn", {"input": 1}, 5)
    db.add_attachments("rdel", "u_start", ["a.txt"])
    from ov.agent.engine.files import run_dir

    (run_dir("rdel") / "note.txt").write_text("x", encoding="utf-8")

    assert httpx.delete(f"{agent_server}/api/runs/rdel").status_code == 200
    assert db.get_thread("rdel") is None and db.load_events("rdel") == []
    assert db.load_messages("rdel") == ([], {}) and db.thread_cost("rdel")["requests"] == 0
    assert not run_dir("rdel").exists() or not any(run_dir("rdel").iterdir())
