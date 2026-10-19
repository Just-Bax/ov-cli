from __future__ import annotations

import pytest

from ov.agent.storage import db


def test_boolean_settings_are_stored_as_booleans():
    saved = db.save_preferences({"notify": 1, "fastModel": "  "})
    assert saved["notify"] is True and saved["fastModel"] == ""
    assert db.get_preferences()["maxSteps"] == 80


def test_notifications_start_off_and_the_tab_badge_on():
    preferences = db.get_preferences()
    assert preferences["notify"] is False and preferences["tabBadge"] is True
    assert db.save_preferences({"notify": True, "tabBadge": False})["notify"] is True


def test_removed_settings_are_refused():
    for removed in ("compactWindow", "followUp", "expandTools"):
        with pytest.raises(ValueError, match="Unknown settings"):
            db.save_preferences({removed: None})
