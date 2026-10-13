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
