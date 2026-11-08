from __future__ import annotations

import pytest


def test_attachment_mentions_follow_the_name_the_file_was_stored_under():
    from ov.agent.engine.mentions import relink, renames

    files = [{"id": "a", "name": "image.png"}, {"id": "b", "name": "my log.txt"}]
    uploaded = [{"name": "image-2.png"}, {"name": "my log.txt"}]
    text = "see [image.png](attachment:image.png) and [my log.txt](attachment:my%20log.txt) in [x](ov:rule/12)"

    assert relink(text, renames(files, uploaded)) == (
        "see [image-2.png](attachment:image-2.png) and [my log.txt](attachment:my%20log.txt) in [x](ov:rule/12)"
    )


def test_picked_skills_are_added_once_after_the_message():
    from ov.agent import skills
    from ov.agent.engine.mentions import with_skills

    name = skills.create("Release notes", "How to write them", "Keep it short.")
    text = f"use [Release notes](skill:{name}) twice [Release notes](skill:{name})"

    expanded = with_skills(text)
    assert expanded.startswith(text)
    assert expanded.count("Keep it short.") == 1
    assert with_skills("no skills here") == "no skills here"


def test_an_unknown_skill_is_an_error():
    from ov.agent.engine.mentions import with_skills
    from ov.agent.engine.run_common import RunError

    with pytest.raises(RunError, match="Unknown skill: gone"):
        with_skills("[Gone](skill:gone)")
