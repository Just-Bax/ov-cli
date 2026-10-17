from __future__ import annotations

from sqlalchemy import update

from ov.agent.storage import db, models
from ov.agent.storage.models import Access, Provider


def test_a_restart_marks_running_runs_interrupted(ov_home):
    db.create_thread("rabc", "t", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    db.update_thread("rabc", status="running")
    db.append_event("rabc", 0, {"type": "status", "status": "running"})
    db.close()
    assert db.list_threads()[0]["status"] == "error"
    assert db.load_events("rabc")[-1]["event"]["status"] == "error"


def test_restart_closes_tools_left_running():
    db.create_thread("r1", "t", Provider.COPILOT, "m", prompt="", instance=None, access=Access.READ)
    db.append_event("r1", 0, {"type": "tool", "tool": {"id": "a", "status": "running"}})
    db.append_event("r1", 1, {"type": "tool", "tool": {"id": "b", "status": "running"}})
    db.append_event("r1", 2, {"type": "tool", "tool": {"id": "b", "status": "ok"}})
    db.close()

    tools = [e["event"]["tool"] for e in db.load_events("r1") if e["event"]["type"] == "tool"]

    assert [(t["id"], t["status"]) for t in tools][-1] == ("a", "error")
    assert sum(t["status"] == "error" for t in tools) == 1


def test_runs_can_be_settled_and_a_follow_up_unsettles_them(logged_in):
    db.create_thread("rsettle", "t", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    db.set_settled("rsettle", True)
    assert db.list_threads()[0]["settled"] is True
    db.set_settled("rsettle", False)
    assert "settled" not in db.list_threads()[0]


def test_run_list_splits_active_and_settled(logged_in):
    for n in range(3):
        db.create_thread(f"rlist{n}", "t", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    db.set_settled("rlist0", True)
    assert {r["id"] for r in db.list_threads(settled=False)} >= {"rlist1", "rlist2"}
    assert [r["id"] for r in db.list_threads(settled=True)] == ["rlist0"]
    assert db.settled_count() == 1


def test_finished_threads_need_attention_until_they_are_seen(ov_home):
    db.create_thread("rdone", "t", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    db.create_thread("rfail", "t", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    assert "attention" not in db.get_thread("rdone")

    db.update_thread("rdone", status="done")
    db.update_thread("rfail", status="error")
    assert db.get_thread("rdone")["attention"] == "done"
    assert db.get_thread("rfail")["attention"] == "failed"

    db.set_seen("rdone")
    db.update_thread("rdone", title="renamed")
    assert "attention" not in db.get_thread("rdone")


def test_a_snoozed_thread_wakes_until_it_is_seen(ov_home):
    db.create_thread("rnap", "t", Provider.COPILOT, "m", prompt="x", instance=None, access=Access.READ)
    db.set_snoozed("rnap", db.now_ms() + 60_000)
    assert "attention" not in db.get_thread("rnap")

    with db._begin() as conn:
        conn.execute(update(models.Thread).where(models.Thread.id == "rnap").values(snoozed_until=db.now_ms() - 1))
    assert db.get_thread("rnap")["attention"] == "woke"

    db.set_seen("rnap")
    assert "attention" not in db.get_thread("rnap")
