from __future__ import annotations

import pytest
from helpers.agent import FakeContext

from ov.agent.tools import data_change
from ov.agent.tools.base import ToolError
from ov.core.errors import ApiError

CURRENT = {
    1: {"TRACKOR_KEY": "S-1", "STATUS": "Active"},
    2: {"TRACKOR_KEY": "S-2", "STATUS": "On Hold"},
    3: {"TRACKOR_KEY": "S-3", "STATUS": "Active"},
}


class FakeClient:
    def __init__(self, values: dict[int, dict], puts: list) -> None:
        self.values = values
        self.puts = puts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def api(self, method, path, params=None, json=None):
        trackor_id = int(path.rsplit("/", 1)[1])
        if method == "PUT":
            if trackor_id == 3:
                raise ApiError(500, "Rule Block hold rejected the change", None, path)
            self.puts.append((trackor_id, json))
            self.values[trackor_id] = {**self.values[trackor_id], **json}
            return None

        class Response:
            def json(self_inner):
                return self.values[trackor_id]

        return Response()


@pytest.fixture
def instance(logged_in, monkeypatch):
    values = {k: dict(v) for k, v in CURRENT.items()}
    puts: list = []
    monkeypatch.setattr(data_change, "open_client", lambda alias: FakeClient(values, puts))
    return values, puts


def _update(ctx: FakeContext, **args) -> str:
    return data_change.TOOLS[0].handler(args, ctx)


ROWS = [{"trackor_id": i, "fields": {"STATUS": "On Hold"}} for i in (1, 2, 3)]


def test_a_read_only_thread_sees_the_change_but_nothing_is_written(instance, tmp_path):
    _, puts = instance
    ctx = FakeContext(tmp_path)

    with pytest.raises(ToolError, match="Read-only"):
        _update(ctx, trackor_type="Site", title="Hold sites", rows=ROWS)

    shown = ctx.events[0]["grid"]
    assert [r["_status"] for r in shown["rows"]] == ["", "unchanged", ""]
    assert shown["rows"][0]["STATUS"] == {"before": "Active", "after": "On Hold"}
    assert shown["change"]["total"] == 2 and shown["change"]["unchanged"] == 1
    assert ctx.events[-1]["grid"]["change"]["state"] == "blocked"
    assert puts == []


def test_an_approved_change_reports_failures_and_can_be_reverted(instance, tmp_path):
    values, puts = instance
    ctx = FakeContext(tmp_path, write=True)

    out = _update(ctx, trackor_type="Site", title="Hold sites", rows=ROWS)

    assert puts == [(1, {"STATUS": "On Hold"})]
    assert "1 updated, 1 failed, 1 already had these values" in out
    assert "S-3 (3): Rule Block hold rejected the change" in out
    final = ctx.events[-1]["grid"]
    assert final["change"]["state"] == "done"
    assert [r["_status"] for r in final["rows"]] == ["updated", "unchanged", "failed"]

    grid_id = final["id"]
    revert = FakeContext(tmp_path, write=True)
    assert "1 updated" in _update(revert, revert=grid_id)
    assert puts[-1] == (1, {"STATUS": "Active"}) and values[1]["STATUS"] == "Active"
    assert revert.events[0]["grid"]["title"] == "Revert: Hold sites"


def test_a_rejected_change_writes_nothing(instance, tmp_path):
    _, puts = instance
    ctx = FakeContext(tmp_path, write=True, approve="Reject")

    with pytest.raises(ToolError, match="rejected"):
        _update(ctx, trackor_type="Site", rows=ROWS)

    assert ctx.events[-1]["grid"]["change"]["state"] == "rejected" and puts == []


def test_rows_need_ids_and_fields(instance, tmp_path):
    with pytest.raises(ToolError, match="trackor_id"):
        _update(FakeContext(tmp_path), trackor_type="Site", rows=[{"trackor_id": "x", "fields": {"A": 1}}])
    with pytest.raises(ToolError, match="No finished data change"):
        _update(FakeContext(tmp_path), revert="grid_missing")
