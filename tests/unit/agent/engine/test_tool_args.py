from __future__ import annotations

import pytest

from ov.agent.engine.run_tools import _tool_args
from ov.agent.tools import tool_named
from ov.agent.tools.base import ToolError
from ov.agent.tools.thread import _question_item


def test_arguments_outside_the_schema_are_named():
    with pytest.raises(ToolError, match="ov_mcp has no argument trackor_types; it takes instance, tool, arguments"):
        _tool_args(tool_named("ov_mcp"), '{"instance": "acme", "tool": "schema_list_fields", "trackor_types": []}')


def test_a_question_with_one_option_says_which_and_what_to_do():
    item = {"question": "Which instance?", "options": [{"label": "acme"}]}
    with pytest.raises(ToolError, match=r'"Which instance\?" has 1 option.*go with that choice'):
        _question_item(item)
