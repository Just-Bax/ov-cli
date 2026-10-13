from __future__ import annotations

from ov.agent.storage import db


def test_a_thread_without_usage_has_no_cost():
    db.create_thread("rold", "Old", "m", prompt="x", instance=None, allow_write=False)
    assert "cost" not in db.list_threads()[0]
    assert db.thread_cost("rold") == {"credits": 0.0, "requests": 0, "tokens": {}, "models": []}


def test_the_cost_report_adds_up_by_day_model_and_thread():
    db.create_thread("ra", "Alpha", "m", prompt="x", instance=None, allow_write=False)
    db.create_thread("rb", "Beta", "m", prompt="x", instance=None, allow_write=False)
    db.add_usage("ra", "opus", "turn", {"input": 100}, 2_000_000_000)
    db.add_usage("ra", "haiku", "step", {"input": 50, "output": 5}, 500_000_000)
    db.add_usage("rb", "opus", "turn", {"output": 10}, 4_000_000_000)

    since = db.now_ms() - 3 * 86_400_000
    report = db.cost_report(since)
    assert report["credits"] == 6.5
    assert report["requests"] == 3
    assert report["tokens"] == {"input": 150, "output": 15}
    assert [m["model"] for m in report["models"]] == ["opus", "haiku"]
    assert [(t["id"], t["title"], t["credits"]) for t in report["threads"]] == [
        ("rb", "Beta", 4.0),
        ("ra", "Alpha", 2.5),
    ]
    assert len(report["days"]) == 4
    assert report["days"][-1]["credits"] == 6.5
    assert db.cost_report(db.now_ms() + 1000)["requests"] == 0
