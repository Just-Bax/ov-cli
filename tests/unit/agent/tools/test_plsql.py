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
    monkeypatch.setitem(plsql._switch, "enabled", True)
    monkeypatch.setattr(plsql, "web_session_alive", lambda alias: True)
    monkeypatch.setattr(plsql, "_execute", lambda alias, block: blocks.append(block) or "1")
    return blocks


def test_the_tool_is_off_unless_the_agent_was_started_with_it(logged_in, tmp_path):
    from ov.agent.tools import tool_specs

    assert "ov_plsql" not in {s["function"]["name"] for s in tool_specs(write=True)}
    with pytest.raises(ToolError, match="ov agent --allow-plsql"):
        plsql.TOOLS[0].handler(ARGS, FakeContext(tmp_path, write=True))


def test_an_ended_web_session_asks_for_a_web_sign_in_before_the_approval(executed, tmp_path, monkeypatch):
    monkeypatch.setattr(plsql, "web_session_alive", lambda alias: False)
    ctx = FakeContext(tmp_path, write=True)

    with pytest.raises(ToolError, match="skipped"):
        plsql.TOOLS[0].handler(ARGS, ctx)
    assert ctx.logins == [("acme.onevizion.test", True)] and ctx.asked == [] and executed == []


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


def test_the_tool_shows_a_card_and_runs_in_the_foreground():
    spec = plsql.TOOLS[0]

    assert not spec.silent
    assert "background" not in spec.spec["function"]["parameters"]["properties"]
