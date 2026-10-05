from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from .cancel import Cancel
from .ovproc import run_ov

EXPORT_PATH = "/v3/components/exports/run"
EXPORT_TIMEOUT_SECONDS = 600
ERROR_CHARS = 400
TYPES = (
    "DB_PACKAGE",
    "RULE",
    "IMPORT",
    "REPORT",
    "NOTIF",
    "WORKFLOW",
    "AUTOMATION",
    "MODULE",
    "CONFIG_FIELD",
    "TRACKOR_TYPE",
    "TRACKOR_FORM",
    "BI_TABLE",
    "RULE_TYPE",
    "SEC_ROLE",
    "WIDGET",
    "WIDGET_PANEL",
    "APPLICATION",
)


class ExportError(Exception):
    pass


def request_args(component_type: str, ids: list[int] | None) -> list[str]:
    if component_type not in TYPES:
        raise ExportError(f"Unknown component type {component_type}. Use one of: {', '.join(TYPES)}.")

    component: dict[str, Any] = {"component_type": component_type}
    if ids is None:
        component["export_all"] = True
    else:
        component["component_ids"] = ids
    body = json.dumps({"filename": "ov-agent", "components": [component]})
    return ["request", "POST", EXPORT_PATH, "-d", body]


def items(xml_text: str) -> list[ET.Element]:
    root = ET.fromstring(xml_text)
    return [item for group in root for item in group]


def fields(item: ET.Element) -> dict[str, str]:
    return {child.tag: (child.text or "") for child in item if not len(child)}


def lists(item: ET.Element) -> dict[str, int]:
    return {child.tag: len(child) for child in item if len(child)}


def export(alias: str, component_type: str, ids: list[int] | None, cancel: Cancel) -> list[ET.Element]:
    result = run_ov(
        ["-i", alias, *request_args(component_type, ids), "--raw"],
        timeout=EXPORT_TIMEOUT_SECONDS,
        cancel=cancel,
    )
    cancel.check()
    if result.code != 0:
        raise ExportError(result.message[:ERROR_CHARS] or f"Component export exited {result.code}")
    return items(result.stdout)
