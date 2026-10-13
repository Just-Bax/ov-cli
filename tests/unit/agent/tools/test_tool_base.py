from __future__ import annotations

from helpers.agent import FakeContext


def test_every_tool_is_in_one_group():
    from ov.agent.tools import TOOL_GROUPS, TOOLS

    grouped = [name for _, _, names in TOOL_GROUPS for name in names]
    assert sorted(grouped) == sorted(t.name for t in TOOLS)
    assert len(grouped) == len(set(grouped))


def test_secrets_are_masked_in_any_tool_output(tmp_path):
    from ov.agent.tools.base import clip

    out = clip('DB_PASSWORD=Xy9abc {"apiKey": "k-123"} max_tokens=32000', FakeContext(tmp_path), "output")
    assert out == 'DB_PASSWORD=*** {"apiKey": "***"} max_tokens=32000'
