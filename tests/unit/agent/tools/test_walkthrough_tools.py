from __future__ import annotations

import pytest
from helpers.agent import FakeContext


def test_walk_plan_creates_a_walkthrough_and_shows_a_card(ov_home, tmp_path):
    from ov.agent.storage import db
    from ov.agent.tools import TOOLS_BY_NAME

    ctx = FakeContext(tmp_path)
    ctx.instance = "dev.onevizion.com"
    out = TOOLS_BY_NAME["walk_plan"].handler(
        {"title": "Smoke test", "goal": "It lists", "steps": ["Open page", "Click New", "  "]},
        ctx,
    )

    (event,) = ctx.events
    walk = event["walkthrough"]
    assert event["type"] == "walkthrough"
    assert walk["instance"] == "dev.onevizion.com"
    assert walk["steps"] == ["Open page", "Click New"]
    assert walk["id"] in out
    assert db.get_walkthrough(walk["id"]) is not None


def test_walk_plan_needs_an_instance(tmp_path):
    from ov.agent.tools import TOOLS_BY_NAME
    from ov.agent.tools.base import ToolError

    ctx = FakeContext(tmp_path)
    ctx.instance = ""
    with pytest.raises(ToolError):
        TOOLS_BY_NAME["walk_plan"].handler({"title": "x", "steps": ["a"]}, ctx)


def test_walk_update_revises_steps_and_reshows_the_card(ov_home, tmp_path):
    from ov.agent.storage import db
    from ov.agent.tools import TOOLS_BY_NAME

    ctx = FakeContext(tmp_path)
    ctx.instance = "dev.onevizion.com"
    TOOLS_BY_NAME["walk_plan"].handler({"title": "First", "steps": ["a", "b"]}, ctx)
    walk_id = ctx.events[0]["walkthrough"]["id"]

    TOOLS_BY_NAME["walk_update"].handler({"id": walk_id, "steps": ["a", "b", "c"]}, ctx)

    assert ctx.events[1]["walkthrough"]["steps"] == ["a", "b", "c"]
    assert db.get_walkthrough(walk_id)["steps"] == ["a", "b", "c"]
