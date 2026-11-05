from __future__ import annotations

import json

import pytest

from ov.agent.engine.cancel import Cancel
from ov.agent.instances import access, components, graph, graph_export
from ov.agent.instances.ovproc import OvResult

TYPES = [{"id": 1, "name": "Project"}, {"id": 2, "name": "Site"}]
TREE = {
    "trackor_type_id": -1,
    "name": "Configuration",
    "children": [{"trackor_type_id": 1, "children": [{"trackor_type_id": 2}]}],
}
RULE_XML = (
    "<COMPONENTS><RULES><RULES_ITEM><RULE_ID>500</RULE_ID><RULE>Set status</RULE><IS_ENABLED>1</IS_ENABLED>"
    "<IS_ASYNC>0</IS_ASYNC><RULE_TYPE>After Configured Field Update</RULE_TYPE>"
    "<PRIMARY_TRACKOR_TYPE>Project</PRIMARY_TRACKOR_TYPE>"
    "<SQL_TEXT>begin pkg_sync.run(:pk); end;</SQL_TEXT>"
    "<BPD_ITEMS><T_BPD_ITEM><PKEY>500</PKEY></T_BPD_ITEM></BPD_ITEMS>"
    "<CONFIG_FIELD_IDNUMS><T_TYPE_SPECIF_OBJ_IDNUM><XITOR_TYPE>Project</XITOR_TYPE>"
    "<OBJECT_NAME>P_STATUS</OBJECT_NAME></T_TYPE_SPECIF_OBJ_IDNUM></CONFIG_FIELD_IDNUMS>"
    "<TRACKOR_TYPE_IDNUMS/></RULES_ITEM></RULES></COMPONENTS>"
)


def _results() -> dict[str, list[dict]]:
    return {
        "CONFIG_FIELD": [
            {"id": "10", "name": "P_STATUS", "trackorType": "Project", "dataType": 4, "pointsTo": ""},
            {"id": "11", "name": "S_PROJECT", "trackorType": "Site", "dataType": 20, "pointsTo": "Project"},
        ],
        "RULE": [
            {
                "id": "500",
                "name": "Set status",
                "enabled": True,
                "async": False,
                "trigger": "After Configured Field Update",
                "trackorType": "Project",
                "bindings": [("CONFIG_FIELD_IDNUMS", "Project", "P_STATUS")],
                "code": "begin pkg_sync.run(:pk); end;",
            }
        ],
        "AUTOMATION": [
            {"id": "7", "name": "Stamp", "enabled": None, "trackorType": "Site", "triggers": [("Site", "S_PROJECT")]}
        ],
        "IMPORT": [{"id": "30", "name": "Sites", "loads": ["Site"], "code": ""}],
        "REPORT": [],
        "NOTIF": [],
        "MODULE": [],
        "DB_PACKAGE": [{"id": "40", "name": "PKG_SYNC", "enabled": None, "trackorType": "", "code": ""}],
    }


def _edges(data: dict) -> set[tuple[str, str, str]]:
    return {(e["source"], e["target"], e["kind"]) for e in data["edges"]}


def test_exports_link_like_the_sql_map():
    edges = _edges(graph_export.assemble(TYPES, TREE, _results()))

    assert ("trackor_type:1", "trackor_type:2", "parent_of") in edges
    assert ("field:10", "trackor_type:1", "field_of") in edges
    assert ("field:11", "trackor_type:1", "points_to") in edges
    assert ("rule:500", "trackor_type:1", "on") in edges
    assert ("rule:500", "field:10", "triggered_by") in edges
    assert ("rule:500", "db_package:40", "calls") in edges
    assert ("automation:7", "field:11", "triggered_by") in edges
    assert ("import:30", "trackor_type:2", "loads") in edges


def test_rules_are_read_from_a_streamed_export(tmp_path):
    path = tmp_path / "rule.xml"
    path.write_text(RULE_XML, encoding="utf-8")
    (rule,) = [graph_export.READERS["RULE"](item) for item in components.streamed_items(path)]
    assert (rule["id"], rule["name"], rule["trackorType"], rule["enabled"]) == ("500", "Set status", "Project", True)
    assert rule["bindings"] == [("CONFIG_FIELD_IDNUMS", "Project", "P_STATUS")]
    assert rule["code"] == "begin pkg_sync.run(:pk); end;"


def test_code_sections_are_named_after_their_part():
    xml = (
        "<COMPONENTS><REPORTS><REPORTS_ITEM><REPORT_NAME>Weekly</REPORT_NAME><REPORT_SQLS>"
        "<T_REPORT_SQL><SQL_NAME>Main</SQL_NAME><SQL_TEXT>select 1 from dual</SQL_TEXT></T_REPORT_SQL>"
        "</REPORT_SQLS></REPORTS_ITEM></REPORTS></COMPONENTS>"
    )
    (item,) = components.items(xml)
    assert components.code_sections(item) == [{"title": "Main: SQL", "code": "select 1 from dual"}]


def test_the_map_is_built_from_exports_without_test_sql(logged_in, monkeypatch):
    monkeypatch.setattr(access, "ensure", lambda alias: {"testSql": False, "export": True})
    monkeypatch.setattr(
        graph_export, "build", lambda alias, cancel, report: (graph_export.assemble(TYPES, TREE, _results()), ["x"])
    )

    built = graph.build("acme")

    assert built["source"] == "export" and built["warnings"] == ["x"]
    assert graph.status("acme")["source"] == "export"


def test_without_sql_or_export_the_map_explains_what_is_missing(logged_in, monkeypatch):
    monkeypatch.setattr(access, "ensure", lambda alias: {"testSql": False, "export": False})
    with pytest.raises(graph.NoAccess, match="neither the Test SQL nor the component export"):
        graph.build("acme")


def test_a_failed_optional_export_becomes_a_warning(logged_in, monkeypatch):
    def fake_run(args, **_):
        if "/v3/trackor_types" in args:
            return OvResult(0, json.dumps(TYPES), "")
        if "/v3/trackor_tree" in args:
            return OvResult(0, json.dumps(TREE), "")

        body = json.loads(args[args.index("-d") + 1])
        component = body["components"][0]["component_type"]
        if component == "RULE":
            return OvResult(5, "", "Error[9478]: Unexpected error.")

        out = args[args.index("--out") + 1]
        with open(out, "w", encoding="utf-8") as handle:
            handle.write("<COMPONENTS><X/></COMPONENTS>")
        return OvResult(0, "", "")

    monkeypatch.setattr(graph_export, "run_ov", fake_run)
    monkeypatch.setattr(components, "run_ov", fake_run)

    linked, warnings = graph_export.build("acme", Cancel(), lambda _: None)

    assert any(w.startswith("rule: the export failed: Error[9478]") for w in warnings)
    assert {n["id"] for n in linked["nodes"]} == {"trackor_type:1", "trackor_type:2"}


def test_packages_are_named_from_their_export(tmp_path):
    path = tmp_path / "packages.xml"
    path.write_text(
        "<COMPONENTS><DB_PACKAGES><DB_PACKAGES_ITEM><DB_PKG_NAME>PKG_SYNC</DB_PKG_NAME>"
        "<DB_PACKAGE_BODY>begin null; end;</DB_PACKAGE_BODY><DB_PACKAGE_ID>40</DB_PACKAGE_ID>"
        "</DB_PACKAGES_ITEM></DB_PACKAGES></COMPONENTS>",
        encoding="utf-8",
    )

    (package,) = [graph_export.READERS["DB_PACKAGE"](item) for item in components.streamed_items(path)]

    assert (package["id"], package["name"]) == ("40", "PKG_SYNC")
