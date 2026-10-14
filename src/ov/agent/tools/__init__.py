from __future__ import annotations

from typing import Any

from ov.agent.tools import datadog, onevizion, pagerduty, thread, workspace
from ov.agent.tools.base import Tool

CORE_TOOLS = [*onevizion.TOOLS, *thread.TOOLS]
TOOLS = [*CORE_TOOLS, *workspace.TOOLS, *datadog.TOOLS, *pagerduty.READ_TOOLS, *pagerduty.WRITE_TOOLS]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def _names(tools: list[Tool]) -> list[str]:
    return [t.name for t in tools]


TOOL_GROUPS: list[tuple[str, str, list[str]]] = [
    (
        "OV CLI",
        "signed-in OneVizion instances",
        ["ov", "ov_sql", "ov_export", "ov_import", "ov_search", "ov_map", "ov_case", "ov_propose"],
    ),
    ("Workspace", "the user's code folder: files, search, edits and commands", _names(workspace.TOOLS)),
    ("Datadog", "logs, metrics, monitors, events and APM", _names(datadog.TOOLS)),
    (
        "PagerDuty",
        "incidents and on-call; changes only while allowed",
        _names([*pagerduty.READ_TOOLS, *pagerduty.WRITE_TOOLS]),
    ),
    ("Skills", "guides for each area", ["skill_read"]),
    ("Run", "the run folder, questions to the user and the result", ["run_read", "run_ask", "run_report"]),
]


def tool_specs(write: bool = False) -> list[dict[str, Any]]:
    offered = [
        *CORE_TOOLS,
        *pagerduty.offered_writers(write),
        *workspace.offered(),
        *datadog.offered(),
        *pagerduty.offered_readers(),
    ]
    return [t.spec for t in offered]


def tool_named(name: str) -> Tool | None:
    return TOOLS_BY_NAME.get(name)
