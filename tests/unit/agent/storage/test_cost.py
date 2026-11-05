from __future__ import annotations

from ov.agent.storage import db
from ov.agent.storage.models import Access


def test_a_thread_without_usage_has_no_cost():
    db.create_thread("rold", "Old", "copilot", "m", instance=None, access=Access.READ)
    assert "cost" not in db.list_threads()[0]
    assert db.thread_cost("rold") == {"amount": 0.0, "requests": 0, "tokens": {}, "models": []}


def test_the_cost_report_adds_up_by_day_model_and_thread():
    db.create_thread("ra", "Alpha", "copilot", "m", instance=None, access=Access.READ)
    db.create_thread("rb", "Beta", "copilot", "m", instance=None, access=Access.READ)
    db.add_usage("ra", "copilot", "opus", "turn", tokens={"input": 100}, nano=2_000_000_000)
    db.add_usage("ra", "copilot", "haiku", "agent", tokens={"input": 50, "output": 5}, nano=500_000_000)
    db.add_usage("rb", "copilot", "opus", "turn", tokens={"output": 10}, nano=4_000_000_000)

    since = db.now_ms() - 3 * 86_400_000
    report = db.cost_report(since, "copilot")
    assert report["amount"] == 6.5
    assert report["requests"] == 3
    assert report["tokens"] == {"input": 150, "output": 15}
    assert [m["model"] for m in report["models"]] == ["opus", "haiku"]
    assert [(t["id"], t["title"], t["amount"]) for t in report["threads"]] == [
        ("rb", "Beta", 4.0),
        ("ra", "Alpha", 2.5),
    ]
    assert len(report["days"]) == 4
    assert report["days"][-1]["amount"] == 6.5
    assert db.cost_report(db.now_ms() + 1000, "copilot")["requests"] == 0
    assert db.cost_report(since, "claude")["requests"] == 0
