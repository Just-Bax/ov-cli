from __future__ import annotations

import pytest
from helpers.agent import FakeContext

from ov.agent.engine.state import empty_state, reduce
from ov.agent.instances import access, datasets
from ov.agent.tools import grid
from ov.agent.tools.base import ToolError

SITES = [{"TRACKOR_ID": 1, "TRACKOR_KEY": "S-1", "STATUS": "Active"}]
KEY_COLUMN = {"key": "TRACKOR_KEY", "type": "trackor", "id_key": "TRACKOR_ID"}


def _show(ctx: FakeContext, **args) -> str:
    return grid.TOOLS[0].handler({"title": "Sites", **args}, ctx)


def test_records_are_shown_as_a_typed_grid(logged_in, tmp_path):
    ctx = FakeContext(tmp_path)
    out = _show(ctx, rows=SITES, columns=[KEY_COLUMN, {"key": "STATUS", "label": "Status", "type": "status"}])

    (event,) = ctx.events
    shown = event["grid"]
    assert event["type"] == "grid" and shown["title"] == "Sites" and shown["total"] == 1
    assert shown["columns"][0] == {
        "key": "TRACKOR_KEY",
        "label": "TRACKOR_KEY",
        "type": "trackor",
        "idKey": "TRACKOR_ID",
    }
    assert shown["baseUrl"] == "https://acme.onevizion.test" and "source" not in shown
    assert "1 rows" in out and "S-1\tActive" in out


def test_columns_are_checked_against_the_data(logged_in, tmp_path):
    ctx = FakeContext(tmp_path)
    with pytest.raises(ToolError, match="Not in the data: STATE"):
        _show(ctx, rows=SITES, columns=[{"key": "STATE", "type": "text"}])
    with pytest.raises(ToolError, match="needs href"):
        _show(ctx, rows=SITES, columns=[{"key": "STATUS", "type": "link"}])
    with pytest.raises(ToolError, match="needs a type"):
        _show(ctx, rows=SITES, columns=[{"key": "STATUS"}])
    with pytest.raises(ToolError, match="exactly one of"):
        _show(ctx, columns=[{"key": "STATUS", "type": "text"}])


def test_sql_grids_mask_secrets_and_keep_their_query(logged_in, tmp_path, monkeypatch):
    calls = []

    def fake_rows(alias, query, limit, cancel):
        calls.append((alias, query, limit))
        return ["NAME", "PASSWORD"], [["svc", "hunter2"]], 1

    monkeypatch.setattr(datasets, "sql_rows", fake_rows)
    ctx = FakeContext(tmp_path)
    _show(ctx, sql="select name, password from module_param;", limit=5000, columns=[{"key": "NAME", "type": "text"}])

    shown = ctx.events[0]["grid"]
    assert calls == [("acme", "select name, password from module_param", 1000)]
    assert shown["rows"] == [{"NAME": "svc", "PASSWORD": "***"}]
    assert shown["source"] == {"kind": "sql", "query": "select name, password from module_param", "limit": 1000}


def test_a_sql_grid_needs_test_sql(logged_in, tmp_path, monkeypatch):
    monkeypatch.setattr(access, "allows", lambda alias, capability: False)
    with pytest.raises(ToolError, match="no Test SQL privilege"):
        _show(FakeContext(tmp_path), sql="select 1 n from dual", columns=[{"key": "N", "type": "number"}])


def test_grid_updates_merge_into_the_thread():
    state = empty_state({"id": "r1", "status": "running"}, "read")
    reduce(state, {"seq": 1, "ts": 1, "event": {"type": "grid", "grid": {"id": "g1", "title": "Sites", "rows": []}}})
    reduce(state, {"seq": 2, "ts": 2, "event": {"type": "grid", "grid": {"id": "g1", "loading": True}}})

    assert state["grids"] == [{"id": "g1", "title": "Sites", "rows": [], "loading": True}]
    assert state["items"] == [{"kind": "grid", "id": "g1"}]
