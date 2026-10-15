from __future__ import annotations

import pytest

from ov.agent import skills


def test_bundled_skills_are_read_only_and_clone_into_custom_ones():
    names = [s["name"] for s in skills.list_skills()]
    assert names[:11] == [
        "working-style",
        "onevizion-basics",
        "ov-cli",
        "workspace",
        "onevizion-reference",
        "plsql-best-practices",
        "oneteam-basics",
        "issue-lifecycle",
        "tce-best-practices",
        "datadog",
        "pagerduty",
    ]

    with pytest.raises(skills.SkillError, match="Clone it"):
        skills.update("ov-cli", {"content": "mine"})
    with pytest.raises(skills.SkillError, match="Turn it off"):
        skills.delete("ov-cli")

    copy = skills.clone("ov-cli")
    listed = {s["name"]: s for s in skills.list_skills()}
    assert listed[copy]["source"] == "custom" and listed[copy]["content"] == listed["ov-cli"]["content"]
    assert not listed["ov-cli"]["enabled"]

    skills.update(copy, {"content": "mine"})
    enabled = {s["name"]: s for s in skills.enabled_skills()}
    assert "ov-cli" not in enabled and enabled[copy]["content"] == "mine"

    skills.update("ov-cli", {"enabled": True})
    assert next(s for s in skills.list_skills() if s["name"] == "ov-cli")["enabled"]


def test_user_skills_get_unique_names():
    first = skills.create("Case replies", "how to reply", "be short")
    second = skills.create("Case replies", "", "")
    assert (first, second) == ("case-replies", "case-replies-2")
    skills.delete(first)
    assert first not in [s["name"] for s in skills.list_skills()]


def test_skills_are_read_on_demand(logged_in):
    from ov.agent.tools import tool_named
    from ov.agent.tools.base import ToolError

    skill = tool_named("skill_read")
    assert skill.handler({"name": "ov-cli"}, None).startswith("# OV CLI\n\n")
    with pytest.raises(ToolError, match="Skills: working-style, onevizion-basics"):
        skill.handler({"name": "datadog"}, None)


def test_bundled_skills_are_ascii_with_trigger_descriptions():
    for skill in skills.bundled():
        text = f"{skill['title']}\n{skill['description']}\n{skill['content']}"
        assert text.isascii(), skill["name"]
        assert skill["description"], skill["name"]
    on_demand = [s for s in skills.bundled() if not s["core"]]
    assert all(s["description"].startswith("Use ") for s in on_demand)
