from __future__ import annotations

from helpers.agent import FakeContext


def test_finish_keeps_existing_matches_and_the_reply(tmp_path):
    from ov.agent.tools import TOOLS_BY_NAME

    ctx = FakeContext(tmp_path)
    outcomes = []
    ctx.finish = outcomes.append
    TOOLS_BY_NAME["run_report"].handler(
        {
            "findings": [{"title": "t", "verdict": "fix", "summary": "s", "evidence": ["e"]}],
            "existing": [{"key": "IT-1", "title": "x", "covers": "partly"}],
            "reply": "Yes, fixed.",
            "time_saved_minutes": 30,
            "time_saved_basis": "b",
        },
        ctx,
    )
    assert outcomes[0]["existing"] == [{"key": "IT-1", "title": "x", "covers": "partly"}]
    assert outcomes[0]["reply"] == "Yes, fixed."


def test_a_change_card_takes_only_known_object_types(tmp_path):
    import pytest
    from helpers.agent import FakeContext

    from ov.agent.tools import tool_named
    from ov.agent.tools.base import ToolError

    ctx = FakeContext(tmp_path)
    card = {"title": "Key by source task", "language": "plsql", "what": "w", "why": "y", "how": "h", "after": "x"}
    with pytest.raises(ToolError, match="entity_type must be one of"):
        tool_named("ov_propose").handler({**card, "entity_type": "DB package (PKG_KAFKA body, WORKMATE)"}, ctx)
    tool_named("ov_propose").handler({**card, "entity_type": "DB Package", "entity_id": "12414"}, ctx)
    shown = ctx.events[-1]["change"]
    assert shown["entityType"] == "db package" and shown["link"].endswith("/admin/dbpackage/Form.do?id=12414")
