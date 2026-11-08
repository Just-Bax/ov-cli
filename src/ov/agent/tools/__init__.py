from __future__ import annotations

from typing import Any

from ov.agent.tools import (
    browser,
    data_change,
    datadog,
    ddl,
    grid,
    mcp,
    onevizion,
    pagerduty,
    plsql,
    thread,
    workspace,
)
from ov.agent.tools.base import Tool

CORE_TOOLS = [*onevizion.TOOLS, *data_change.TOOLS, *plsql.TOOLS, *grid.TOOLS, *thread.TOOLS]
TOOLS = [
    *CORE_TOOLS,
    *mcp.TOOLS,
    *ddl.TOOLS,
    *browser.MAIN,
    *workspace.TOOLS,
    *datadog.TOOLS,
    *pagerduty.READ_TOOLS,
    *pagerduty.WRITE_TOOLS,
]
TOOLS_BY_NAME = {t.name: t for t in [*TOOLS, *browser.HANDS]}


def _names(tools: list[Tool]) -> list[str]:
    return [t.name for t in tools]


TOOL_GROUPS: list[tuple[str, str, list[str]]] = [
    (
        "OV CLI",
        "signed-in OneVizion instances",
        [
            "ov",
            "ov_sql",
            "ov_export",
            "ov_import",
            "ov_search",
            "ov_map",
            "ov_update",
            "ov_plsql",
            "ov_mcp",
            "ov_ddl",
            "ov_case",
            "ov_propose",
        ],
    ),
    (
        "Browser",
        "the OneVizion web UI in a live browser the user watches: snapshot, then mouse and keyboard like a person",
        _names(browser.MAIN),
    ),
    ("Workspace", "the user's code folder: files, search, edits and commands", _names(workspace.TOOLS)),
    ("Datadog", "logs, metrics, monitors, events and APM", _names(datadog.TOOLS)),
    (
        "PagerDuty",
        "incidents and on-call; changes only while allowed",
        _names([*pagerduty.READ_TOOLS, *pagerduty.WRITE_TOOLS]),
    ),
    ("Skills", "guides for each area", ["skill_read"]),
    (
        "Run",
        "the run folder, other threads, waiting, questions to the user and the result",
        ["run_read", "thread_read", "thread_search", "run_grid", "run_wait", "run_ask", "run_report"],
    ),
]


def tool_specs(write: bool = False) -> list[dict[str, Any]]:
    offered = [
        *CORE_TOOLS,
        *mcp.offered(),
        *ddl.offered(),
        *browser.MAIN,
        *pagerduty.offered_writers(write),
        *workspace.offered(),
        *datadog.offered(),
        *pagerduty.offered_readers(),
    ]
    return [t.spec for t in offered]


def tool_named(name: str) -> Tool | None:
    return TOOLS_BY_NAME.get(name)
