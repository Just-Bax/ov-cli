from __future__ import annotations

import json
import tempfile
import threading
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ov.agent.engine.cancel import Cancel
from ov.agent.instances import components
from ov.agent.instances.components import text_of
from ov.agent.instances.linking import Builder, Refs, as_number
from ov.agent.instances.ovproc import run_ov

API_TIMEOUT_SECONDS = 120
ERROR_CHARS = 400
EXPORT_WORKERS = 4
ROOT_TRACKOR_TYPE = -1
TRACKOR_TYPES_REQUEST = ("request", "GET", "/v3/trackor_types", "--json")
TRACKOR_TREE_REQUEST = ("request", "GET", "/v3/trackor_tree", "--json")
REQUIRED = ("CONFIG_FIELD",)
SKIPPED_WORKFLOWS = "workflows: not read, because exporting every workflow version takes too long without Test SQL"
ENABLED_TAGS = ("IS_ENABLED", "ENABLED")
BINDING_KINDS = {
    "TRACKOR_TYPE_IDNUMS": "trackor_type",
    "IMPORT_IDNUMS": "import",
    "REPORT_IDNUMS": "report",
}


class ExportGraphError(Exception):
    pass


Row = dict[str, Any]


def _enabled(item: ET.Element) -> bool | None:
    value = next((text_of(item, tag) for tag in ENABLED_TAGS if text_of(item, tag)), "")
    return None if not value else value != "0"


def _code(item: ET.Element) -> str:
    return "\n".join(section["code"] for section in components.code_sections(item))


def _field(item: ET.Element) -> Row:
    return {
        "id": text_of(item, "CONFIG_FIELD_ID"),
        "name": text_of(item, "CONFIG_FIELD_NAME"),
        "trackorType": text_of(item, "TRACKOR_TYPE"),
        "dataType": as_number(text_of(item, "DATA_TYPE")),
        "pointsTo": text_of(item, "OBJ_TRACKOR_TYPE"),
    }


def _bindings(item: ET.Element) -> list[tuple[str, str, str]]:
    found = []
    for group in item:
        if not group.tag.endswith("_IDNUMS"):
            continue
        for entry in group:
            found.append((group.tag, text_of(entry, "XITOR_TYPE"), text_of(entry, "OBJECT_NAME")))
    return found


def _rule(item: ET.Element) -> Row:
    return {
        "id": text_of(item, "RULE_ID"),
        "name": text_of(item, "RULE"),
        "enabled": _enabled(item),
        "async": text_of(item, "IS_ASYNC") == "1",
        "trigger": text_of(item, "RULE_TYPE"),
        "trackorType": text_of(item, "PRIMARY_TRACKOR_TYPE"),
        "bindings": _bindings(item),
        "code": _code(item),
    }


def _automation(item: ET.Element) -> Row:
    triggers = [
        (text_of(cf, "TRACKOR_TYPE"), text_of(cf, "CONFIG_FIELD_NAME")) for cf in item.iter("T_BPL_AUTOM_TRIGGER_CF")
    ]
    return {
        "id": text_of(item, "AUTOM_ID"),
        "name": text_of(item, "AUTOM_NAME"),
        "enabled": _enabled(item),
        "trackorType": text_of(item, "TRACKOR_TYPE"),
        "triggers": triggers,
    }


def _import(item: ET.Element) -> Row:
    return {
        "id": text_of(item, "IMP_SPEC_ID"),
        "name": text_of(item, "NAME"),
        "loads": sorted({text_of(entity, "TRACKOR_TYPE") for entity in item.iter("T_IMP_ENTITY")} - {""}),
        "code": _code(item),
    }


def _named(id_tag: str, name_tag: str, with_code: bool = True) -> Callable[[ET.Element], Row]:
    def read(item: ET.Element) -> Row:
        row = {
            "id": text_of(item, id_tag),
            "name": text_of(item, name_tag),
            "enabled": _enabled(item),
            "trackorType": text_of(item, "TRACKOR_TYPE"),
        }
        return {**row, "code": _code(item)} if with_code else row

    return read


READERS: dict[str, Callable[[ET.Element], Row]] = {
    "CONFIG_FIELD": _field,
    "RULE": _rule,
    "AUTOMATION": _automation,
    "IMPORT": _import,
    "REPORT": _named("REPORT_FILE_ID", "REPORT_NAME"),
    "NOTIF": _named("NOTIF_ID", "NOTIF_NAME"),
    "MODULE": _named("MODULE_ID", "MODULE_NAME", with_code=False),
    "DB_PACKAGE": _named("DB_PACKAGE_ID", "DB_PKG_NAME"),
}


def _api(alias: str, request: tuple[str, ...], cancel: Cancel) -> Any:
    result = run_ov(["-i", alias, *request], timeout=API_TIMEOUT_SECONDS, cancel=cancel)
    cancel.check()
    if result.code != 0:
        raise ExportGraphError(result.message[:ERROR_CHARS] or f"ov exited {result.code}")
    return json.loads(result.stdout)


def _exported(alias: str, component_type: str, folder: Path, cancel: Cancel) -> list[Row]:
    path = folder / f"{component_type.lower()}.xml"
    components.export_to_file(alias, component_type, path, cancel)
    read = READERS[component_type]
    return [read(item) for item in components.streamed_items(path)]


def _read_exports(alias: str, cancel: Cancel, report: Callable[[str], None]) -> tuple[dict[str, list[Row]], list[str]]:
    results: dict[str, list[Row]] = {}
    warnings = [SKIPPED_WORKFLOWS]
    lock = threading.Lock()

    with tempfile.TemporaryDirectory(prefix="ov-map-") as folder:

        def fetch(component_type: str) -> None:
            try:
                rows = _exported(alias, component_type, Path(folder), cancel)
            except components.ExportError as exc:
                if component_type in REQUIRED:
                    raise ExportGraphError(f"The {component_type} export failed: {exc}") from None
                with lock:
                    warnings.append(f"{component_type.lower()}: the export failed: {exc}")
                rows = []

            with lock:
                results[component_type] = rows
                report(f"Exported {len(results)} of {len(READERS)} component types")

        with ThreadPoolExecutor(max_workers=EXPORT_WORKERS) as pool:
            for future in [pool.submit(fetch, name) for name in READERS]:
                future.result()

    return results, warnings


def _tree_edges(node: Row, b: Builder) -> None:
    parent = node.get("trackor_type_id")
    for child in node.get("children") or []:
        if parent != ROOT_TRACKOR_TYPE:
            b.edge(f"trackor_type:{parent}", f"trackor_type:{child['trackor_type_id']}", "parent_of")
        _tree_edges(child, b)


class _Names:
    def __init__(self, b: Builder) -> None:
        self.by_kind: dict[tuple[str, str], str] = {}
        for node in b.nodes.values():
            self.by_kind.setdefault((node["type"], node["name"].lower()), node["id"])
        self.fields: dict[tuple[str, str], str] = {}

    def of(self, kind: str, name: str) -> str | None:
        return self.by_kind.get((kind, name.lower()))

    def field(self, trackor_type: str, name: str) -> str | None:
        return self.fields.get((trackor_type.lower(), name.lower()))


def _add_nodes(b: Builder, types: list[Row], r: dict[str, list[Row]]) -> None:
    for row in types:
        b.node("trackor_type", row["id"], row["name"])
    for row in r["CONFIG_FIELD"]:
        b.node("field", row["id"], row["name"], dataType=row["dataType"])
    for row in r["RULE"]:
        b.node(
            "rule", row["id"], row["name"], enabled=row["enabled"], trigger=row["trigger"] or None, async_=row["async"]
        )
    for kind, component_type in (
        ("automation", "AUTOMATION"),
        ("notification", "NOTIF"),
        ("module", "MODULE"),
        ("import", "IMPORT"),
        ("report", "REPORT"),
        ("db_package", "DB_PACKAGE"),
    ):
        for row in r[component_type]:
            b.node(kind, row["id"], row["name"], enabled=row.get("enabled"))


def _add_field_edges(b: Builder, names: _Names, r: dict[str, list[Row]]) -> None:
    for row in r["CONFIG_FIELD"]:
        field = f"field:{row['id']}"
        owner = names.of("trackor_type", row["trackorType"])
        if owner is None:
            continue

        names.fields[(row["trackorType"].lower(), row["name"].lower())] = field
        b.edge(field, owner, "field_of")
        target = names.of("trackor_type", row["pointsTo"]) if row["pointsTo"] else None
        if target is not None:
            b.edge(field, target, "points_to")


def _binding_target(names: _Names, group: str, trackor_type: str, name: str) -> str | None:
    if group == "CONFIG_FIELD_IDNUMS":
        return names.field(trackor_type, name)
    kind = BINDING_KINDS.get(group)
    return names.of(kind, name or trackor_type) if kind else None


def _link(b: Builder, source: str, target: str | None, kind: str) -> None:
    if target is not None:
        b.edge(source, target, kind)


def _add_rule_edges(b: Builder, names: _Names, rows: list[Row]) -> None:
    for row in rows:
        rule = f"rule:{row['id']}"
        _link(b, rule, names.of("trackor_type", row["trackorType"]), "on")
        for group, trackor_type, name in row["bindings"]:
            _link(b, rule, _binding_target(names, group, trackor_type, name), "triggered_by")


def _add_automation_edges(b: Builder, names: _Names, rows: list[Row]) -> None:
    for row in rows:
        automation = f"automation:{row['id']}"
        _link(b, automation, names.of("trackor_type", row["trackorType"]), "on")
        for trackor_type, name in row["triggers"]:
            _link(b, automation, names.field(trackor_type, name), "triggered_by")


def _add_behaviour_edges(b: Builder, names: _Names, r: dict[str, list[Row]]) -> None:
    _add_rule_edges(b, names, r["RULE"])
    _add_automation_edges(b, names, r["AUTOMATION"])
    for row in r["NOTIF"]:
        _link(b, f"notification:{row['id']}", names.of("trackor_type", row["trackorType"]), "on")
    for row in r["IMPORT"]:
        for loaded in row["loads"]:
            _link(b, f"import:{row['id']}", names.of("trackor_type", loaded), "loads")


def _add_code_edges(b: Builder, r: dict[str, list[Row]]) -> None:
    refs = Refs(b.nodes, b.edges)
    for kind, component_type in (
        ("rule", "RULE"),
        ("import", "IMPORT"),
        ("report", "REPORT"),
        ("notification", "NOTIF"),
        ("db_package", "DB_PACKAGE"),
    ):
        for row in r[component_type]:
            refs.link(b, f"{kind}:{row['id']}", row["code"])


def assemble(types: list[Row], tree: Row, r: dict[str, list[Row]]) -> dict[str, Any]:
    b = Builder()
    _add_nodes(b, types, r)
    _tree_edges(tree, b)
    names = _Names(b)
    _add_field_edges(b, names, r)
    _add_behaviour_edges(b, names, r)
    _add_code_edges(b, r)
    edges = [{"source": s, "target": t, "kind": k, **({"code": True} if c else {})} for s, t, k, c in sorted(b.edges)]
    return {"nodes": list(b.nodes.values()), "edges": edges}


def build(alias: str, cancel: Cancel, report: Callable[[str], None]) -> tuple[dict[str, Any], list[str]]:
    report("Reading trackor types")
    types = _api(alias, TRACKOR_TYPES_REQUEST, cancel)
    tree = _api(alias, TRACKOR_TREE_REQUEST, cancel)
    results, warnings = _read_exports(alias, cancel, report)
    report("Linking objects")
    return assemble(types, tree, results), warnings
