from __future__ import annotations

from ov.agent.storage import db


def test_boolean_settings_are_stored_as_booleans():
    saved = db.save_preferences({"expandTools": 1, "fastModel": "  "})
    assert saved["expandTools"] is True and saved["fastModel"] == ""
    assert db.get_preferences()["maxSteps"] == 80
