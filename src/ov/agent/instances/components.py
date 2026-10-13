from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from ov.agent.engine.cancel import Cancel
from ov.agent.instances.ovproc import run_ov

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


IMPORT_PATH = "/v3/components/imports/run"
IMPORT_TYPES = (
    *TYPES,
    "CONFIG_GROUP",
    "CONFIG_APPLET",
    "DYNAMIC_VTABLE",
    "VIEW_OPT",
    "FILTER_OPT",
    "BPD_ITEM",
    "TRACKOR_TOUR",
    "WORKPLAN",
    "RELATION_TYPE",
)
IMPORT_MODES = (
    "UNASSING_ALL_MENU",
    "MERGE_APP_ITEMS",
    "THROW_IF_EXIST",
    "SKIP_IF_EXIST",
    "UPDATE_IF_EXIST",
    "DONT_MODIFY",
    "APPEND",
    "REPLACE",
    "MERGE",
    "DONT_ASSIGN_TO_TREE",
    "ASSIGN_TO_ROOT",
    "IMPORT_RELATIONS",
    "IMPORT_RELATIONS_ONLY",
    "USE_EXIST",
)
IMPORT_MESSAGE_CHARS = 300


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


def _selection(entry: dict[str, Any]) -> dict[str, Any]:
    component_type = str(entry.get("component_type", "")).upper()
    if component_type not in IMPORT_TYPES:
        raise ExportError(f"Unknown component type {component_type}. Use one of: {', '.join(IMPORT_TYPES)}.")

    picked: dict[str, Any] = {"component_type": component_type}
    if entry.get("mode"):
        mode = str(entry["mode"]).upper()
        if mode not in IMPORT_MODES:
            raise ExportError(f"Unknown import mode {mode}. Use one of: {', '.join(IMPORT_MODES)}.")
        picked["mode"] = mode
    if entry.get("ids"):
        picked["components"] = [{"id": int(i)} for i in entry["ids"]]
    return picked


def import_args(file: str, selection: list[dict[str, Any]], dry_run: bool) -> list[str]:
    args = ["request", "POST", IMPORT_PATH, "-q", f"is_dry_run={str(dry_run).lower()}"]
    args += ["-q", f"is_import_all={str(not selection).lower()}", "--file", f"file=@{file}"]
    if selection:
        args += ["--field", "components:=" + json.dumps([_selection(entry) for entry in selection])]
    return args


def import_summary(response: str) -> str:
    try:
        results = json.loads(response)
    except json.JSONDecodeError:
        raise ExportError(f"The import returned something that is not JSON: {response[:ERROR_CHARS]}") from None
    if not isinstance(results, list):
        raise ExportError(f"The import returned an unexpected shape: {response[:ERROR_CHARS]}")

    lines = []
    for result in results:
        name = result.get("component") or result.get("id")
        lines.append(f"{result.get('component_type')} {name}: {result.get('status')}")
        lines += [
            f"  {m.get('status')}: {(m.get('message') or m.get('full_message') or '')[:IMPORT_MESSAGE_CHARS]}"
            for m in result.get("messages") or []
        ]
    return "\n".join(lines) or "Nothing was imported."
