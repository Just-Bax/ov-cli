from __future__ import annotations

import pytest
from helpers.agent import FakeContext

from ov.agent.tools import plsql
from ov.agent.tools.base import ToolError

BLOCK = "begin\n  update rule set is_enabled = 0 where rule_id = 42;\n  dbms_output.put_line(sql%rowcount);\nend;"
ARGS = {"purpose": "Disable rule 42", "block": BLOCK}


@pytest.fixture
def executed(logged_in, monkeypatch):
    blocks: list[str] = []
    monkeypatch.setattr(plsql, "_execute", lambda alias, block: blocks.append(block) or "1")
    return blocks


def test_a_block_runs_only_after_the_user_approves_it(executed, tmp_path):
    ctx = FakeContext(tmp_path, write=True)

    assert plsql.TOOLS[0].handler(ARGS, ctx) == "1"
    assert executed == [BLOCK] and ctx.asked == [BLOCK]


@pytest.mark.parametrize("mode", ["auto", "full"])
def test_every_access_mode_still_asks(executed, tmp_path, mode):
    ctx = FakeContext(tmp_path, write=True, approve="Reject", **{mode: True})

    with pytest.raises(ToolError, match="rejected"):
        plsql.TOOLS[0].handler(ARGS, ctx)
    assert executed == [] and ctx.asked == [BLOCK]


def test_a_read_only_thread_never_runs_a_block(executed, tmp_path):
    ctx = FakeContext(tmp_path)

    with pytest.raises(ToolError, match="Read-only"):
        plsql.TOOLS[0].handler(ARGS, ctx)
    assert executed == [] and ctx.asked == []


def test_a_rejection_note_goes_back_to_the_agent(executed, tmp_path):
    ctx = FakeContext(tmp_path, write=True, approve="Reject", note="only on dev")

    with pytest.raises(ToolError, match="only on dev"):
        plsql.TOOLS[0].handler(ARGS, ctx)
