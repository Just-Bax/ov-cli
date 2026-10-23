from __future__ import annotations

import json

import pytest
from helpers.agent import FakeContext

from ov.agent.engine.cancel import Cancelled
from ov.agent.instances.ovproc import OvResult
from ov.agent.tools import tool_named


def _counts(*values: str):
    replies = iter(values)

    def fake(args, **_):
        body = {"status": "SUCCESS", "columns": ["N"], "rows": [{"cells": [next(replies)]}]}
        return OvResult(0, json.dumps(body), "")

    return fake


def _waits(ctx, monkeypatch) -> list[float]:
    waited: list[float] = []
    monkeypatch.setattr(ctx.cancel, "wait", lambda seconds: waited.append(seconds) or False)
    return waited


def test_waiting_on_a_query_returns_as_soon_as_its_result_changes(logged_in, tmp_path, monkeypatch):
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", _counts("1", "1", "2"))
    ctx = FakeContext(tmp_path)
    waited = _waits(ctx, monkeypatch)

    out = tool_named("run_wait").handler({"seconds": 300, "sql": "select n from t", "every": 60}, ctx)

    assert out.startswith("The result changed after 120s:") and "\n2" in out
    assert waited == [60, 60]


def test_a_query_that_never_changes_reports_its_last_result(logged_in, tmp_path, monkeypatch):
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", _counts("1", "1", "1", "1"))
    ctx = FakeContext(tmp_path)
    waited = _waits(ctx, monkeypatch)

    out = tool_named("run_wait").handler({"seconds": 25, "sql": "select n from t", "every": 10}, ctx)

    assert out.startswith("No change in 25s. Last result:")
    assert waited == [10, 10, 5]


def test_polls_are_never_closer_than_the_minimum(logged_in, tmp_path, monkeypatch):
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", _counts("1", "2"))
    ctx = FakeContext(tmp_path)
    waited = _waits(ctx, monkeypatch)

    tool_named("run_wait").handler({"seconds": 60, "sql": "select n from t", "every": 1}, ctx)

    assert waited == [10]


def test_waiting_without_a_query_just_waits_until_stopped(logged_in, tmp_path, monkeypatch):
    ctx = FakeContext(tmp_path)
    waited = _waits(ctx, monkeypatch)
    assert tool_named("run_wait").handler({"seconds": 5}, ctx) == "Waited 5s."
    assert waited == [5]

    stopped = FakeContext(tmp_path)
    stopped.cancel.set()
    with pytest.raises(Cancelled):
        tool_named("run_wait").handler({"seconds": 5}, stopped)
