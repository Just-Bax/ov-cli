from __future__ import annotations

import pytest

from ov.agent.integrations.copilot import Usage, usage_of
from ov.agent.storage import db

COPILOT_USAGE = {
    "token_details": [
        {"token_type": "input", "token_count": 12000},
        {"token_type": "cache_read", "token_count": 3000},
        {"token_type": "output", "token_count": 40},
    ],
    "total_nano_aiu": 4_900_000_000,
}


def test_copilot_usage_is_read_from_a_reply():
    assert usage_of({"choices": []}) is None
    usage = usage_of({"copilot_usage": COPILOT_USAGE})
    assert usage == Usage(tokens={"input": 12000, "cache_read": 3000, "output": 40}, nano=4_900_000_000)


def test_reasoning_picks_the_nearest_level_the_model_accepts(monkeypatch):
    from ov.agent.integrations import copilot

    monkeypatch.setattr(
        copilot,
        "list_models",
        lambda: [
            {"id": "big", "reasoning": ["low", "medium", "high", "xhigh", "max"]},
            {"id": "mini", "reasoning": ["low", "medium", "high"]},
            {"id": "old", "reasoning": []},
        ],
    )
    assert copilot.reasoning_for("big", "max") == "max"
    assert copilot.reasoning_for("mini", "max") == "high"
    assert copilot.reasoning_for("mini", "none") == "low"
    assert copilot.reasoning_for("old", "high") is None
    assert copilot.reasoning_for("big", "") is None
    with pytest.raises(ValueError):
        db.save_preferences({"reasoning": "huge"})
    assert db.save_preferences({"reasoning": "xhigh"})["reasoning"] == "xhigh"
