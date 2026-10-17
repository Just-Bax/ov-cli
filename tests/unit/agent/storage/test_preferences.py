from __future__ import annotations

import pytest

from ov.agent.storage import db


def test_boolean_settings_are_stored_as_booleans():
    saved = db.save_preferences({"expandTools": 1, "fastModel": "  "})
    assert saved["expandTools"] is True and saved["fastModel"] == ""
    assert db.get_preferences()["maxSteps"] == 80


def test_notifications_start_off_and_the_tab_badge_on():
    preferences = db.get_preferences()
    assert preferences["notify"] is False and preferences["tabBadge"] is True
    assert db.save_preferences({"notify": True, "tabBadge": False})["notify"] is True


def test_the_compact_window_is_a_token_count_or_the_models_own():
    assert db.get_preferences()["compactWindow"] is None
    assert db.save_preferences({"compactWindow": 400_000})["compactWindow"] == 400_000
    assert db.save_preferences({"compactWindow": None})["compactWindow"] is None
    for wrong in (10, "200000", True, 5_000_000):
        with pytest.raises(ValueError, match="compactWindow"):
            db.save_preferences({"compactWindow": wrong})
