from __future__ import annotations

from helpers.sessions import BASE_URL

from ov.agent.storage import db
from ov.agent.storage.models import Access


def test_forgetting_an_instance_removes_its_local_data_but_keeps_runs(logged_in):
    from ov.agent.instances import graph
    from ov.agent.instances.forget import forget, prune
    from ov.agent.integrations import datadog
    from ov.onevizion import session as session_store

    for alias in ("acme", "gone"):
        graph.graph_file(alias).write_text("{}", encoding="utf-8")
        db.create_thread(f"r{alias}", "t", "copilot", "m", instance=alias, access=Access.READ)
    db.create_thread("rcase", "t", "copilot", "m", instance="acme.onevizion.test", access=Access.READ)

    datadog.save_matches({"acme": "host:a", "gone": "host:b"})

    prune()
    assert not graph.graph_file("gone").exists() and graph.graph_file("acme").exists()
    assert datadog.load_state()["matches"] == {"acme": "host:a"}

    session_store.remove("acme")
    forget("acme", BASE_URL)
    assert not graph.graph_file("acme").exists()
    assert datadog.load_state()["matches"] == {}
    assert {r["id"] for r in db.list_threads()} == {"racme", "rgone", "rcase"}
