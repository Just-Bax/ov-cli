from __future__ import annotations


def test_the_prompt_lists_tools_by_group(logged_in):
    from ov.agent.engine.prompt import system_prompt

    text = system_prompt(False, "")
    assert (
        "- OV CLI (signed-in OneVizion instances): ov, ov_sql, ov_export, ov_import, ov_search, ov_map, ov_case" in text
    )
    assert "Datadog (logs" not in text
    assert "- datadog: " not in text and "Workspace: none set" in text
    assert "## OV CLI" in text and "## OneVizion Basics" in text and "- ov-cli: " not in text
    assert text.index("# Skills to read") < text.index("# Core skills") < text.index("## OV CLI")
