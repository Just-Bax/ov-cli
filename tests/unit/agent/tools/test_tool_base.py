from __future__ import annotations

import pytest
from helpers.agent import FakeContext

from ov.agent.tools import TOOL_GROUPS, TOOLS
from ov.agent.tools.base import ToolError, approved, clip


def test_every_tool_is_in_one_group():
    grouped = [name for _, _, names in TOOL_GROUPS for name in names]
    assert sorted(grouped) == sorted(t.name for t in TOOLS)
    assert len(grouped) == len(set(grouped))


def test_secrets_are_masked_in_any_tool_output(tmp_path):
    out = clip('DB_PASSWORD=Xy9abc {"apiKey": "k-123"} max_tokens=32000', FakeContext(tmp_path), "output")
    assert out == 'DB_PASSWORD=*** {"apiKey": "***"} max_tokens=32000'


def test_ask_first_asks_for_every_change(tmp_path):
    ctx = FakeContext(tmp_path, write=True)
    assert approved(ctx, "Save?", "click Save")
    assert ctx.asked == ["click Save"] and ctx.judged == []


def test_auto_applies_routine_changes_without_asking(tmp_path):
    ctx = FakeContext(tmp_path, write=True, auto=True)
    assert approved(ctx, "Save?", "click Save")
    assert ctx.asked == [] and ctx.judged == ["Save?\nclick Save"]


def test_auto_still_asks_for_risky_changes(tmp_path):
    ctx = FakeContext(tmp_path, write=True, auto=True, risky=True, approve="Reject")
    assert not approved(ctx, "Delete?", "click Delete")
    assert ctx.asked == ["click Delete"] and ctx.reasons == ["it deletes data"]


def test_a_rejection_note_reaches_the_agent(tmp_path):
    ctx = FakeContext(tmp_path, write=True, approve="Reject", note="use the test instance")
    with pytest.raises(ToolError, match="said: use the test instance"):
        approved(ctx, "Save?", "click Save")


def test_full_access_never_checks_or_asks(tmp_path):
    ctx = FakeContext(tmp_path, write=True, full=True, risky=True)
    assert approved(ctx, "Delete?", "click Delete")
    assert ctx.asked == [] and ctx.judged == []
