from __future__ import annotations

from ov.agent.storage import db
from ov.agent.storage.models import Access


def test_the_prompt_lists_tools_by_group(logged_in):
    from ov.agent.engine.prompt import system_prompt

    text = system_prompt(Access.READ, "")

    tools = "ov, ov_sql, ov_export, ov_import, ov_search, ov_map, ov_update, ov_case, ov_propose"
    assert f"- OV CLI (signed-in OneVizion instances): {tools}\n" in text
    assert "run_read, thread_read, run_grid, run_wait" in text
    assert "access not checked yet" in text
    assert "Datadog (logs" not in text
    assert "- datadog: " not in text and "Workspace: none set" in text
    assert "## OV CLI" in text and "## OneVizion Basics" in text and "- ov-cli: " not in text
    assert text.index("# Skills to read") < text.index("# Core skills") < text.index("## OV CLI")


def test_the_profile_is_added_only_when_the_user_filled_it_in(logged_in):
    from ov.agent.engine.prompt import system_prompt

    assert "# About the user" not in system_prompt(Access.READ, "")

    db.save_preferences({"fullName": "  Ada Lovelace ", "instructions": "Keep replies short.\nNo markdown."})
    text = system_prompt(Access.READ, "")
    about = text[text.index("# About the user") : text.index("# Tools by group")]
    assert "Name: Ada Lovelace" in about and "Keep replies short.\nNo markdown." in about
    assert db.get_preferences()["fullName"] == "Ada Lovelace"
