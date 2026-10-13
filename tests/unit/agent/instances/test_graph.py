from __future__ import annotations

import json

import pytest
from helpers.sessions import BASE_URL, seed_session

from ov.agent.instances import graph
from ov.agent.tools import TOOLS_BY_NAME
from ov.core.paths import write_atomic


def rows(**tables):
    empty = {name: [] for name in [*graph.QUERIES, *graph.EXPORTS]}
    return {**empty, **tables}


RESULTS = rows(
    trackor_types=[
        {"XITOR_TYPE_ID": "1", "XITOR_TYPE": "Project"},
        {"XITOR_TYPE_ID": "2", "XITOR_TYPE": "Site"},
    ],
    relations=[{"PARENT_TYPE_ID": "1", "CHILD_TYPE_ID": "2"}],
    fields=[
        {"CONFIG_FIELD_ID": "100100100", "CONFIG_FIELD_NAME": "P_STATUS", "XITOR_TYPE_ID": "1"},
        {
            "CONFIG_FIELD_ID": "100100101",
            "CONFIG_FIELD_NAME": "P_SITE",
            "XITOR_TYPE_ID": "1",
            "OBJ_XITOR_TYPE_ID": "2",
        },
        {"CONFIG_FIELD_ID": "100100102", "CONFIG_FIELD_NAME": "DUPE", "XITOR_TYPE_ID": "1"},
        {"CONFIG_FIELD_ID": "100100103", "CONFIG_FIELD_NAME": "DUPE", "XITOR_TYPE_ID": "2"},
    ],
    rules=[{"RULE_ID": "500", "RULE": "Set status", "IS_ENABLED": "1", "RULE_TYPE": "Field updated"}],
    rule_bindings=[{"RULE_ID": "500", "ID_NUM": "100100101"}],
    rule_code=[
        {
            "RULE_ID": "500",
            "CODE0": "v := 100100100/*P_STATUS*/; ",
            "CODE1": "x := 'DUPE'; y := id.project.cf.p_site; Site",
        }
    ],
    imports=[{"IMP_SPEC_ID": "7", "NAME": "Project load"}],
    import_entities=[{"IMP_SPEC_ID": "7", "XITOR_TYPE_ID": "1"}],
    invalid=[{"COMPONENT_ID": "4", "ENTITY_ID": "500"}],
    packages=[
        {"DB_PACKAGE_ID": "900", "DB_PACKAGE_NAME": "PKG_A"},
        {"DB_PACKAGE_ID": "901", "DB_PACKAGE_NAME": "PKG_B"},
    ],
    package_code=[
        {"DB_PACKAGE_ID": "900", "BODY": "xitor_type_id = id.site.tt; PKG_B.run; id.get('id.imp.project_load');"},
        {"DB_PACKAGE_ID": "901", "BODY": "v := id.project.rel.site;"},
    ],
)


def test_links_come_from_keys_and_code():
    g = graph._assemble(RESULTS)
    edges = {(e["source"], e["target"], e["kind"]) for e in g["edges"]}

    assert ("trackor_type:1", "trackor_type:2", "parent_of") in edges
    assert ("field:100100101", "trackor_type:2", "points_to") in edges
    assert ("rule:500", "field:100100101", "triggered_by") in edges
    assert ("rule:500", "field:100100100", "uses") in edges
    assert ("rule:500", "field:100100101", "uses") in edges
    assert ("import:7", "trackor_type:1", "loads") in edges
    assert ("db_package:900", "trackor_type:2", "uses") in edges
    assert ("db_package:900", "import:7", "uses") in edges
    assert ("db_package:900", "db_package:901", "calls") in edges
    assert ("db_package:901", "trackor_type:1", "uses") in edges
    assert ("rule:500", "trackor_type:2", "uses") not in edges
    assert not any(t in ("field:100100102", "field:100100103") for _, t, k in edges if k == "uses")


def test_invalid_objects_are_flagged():
    g = graph._assemble(RESULTS)
    rule = next(n for n in g["nodes"] if n["id"] == "rule:500")
    assert rule["invalid"] and rule["trigger"] == "Field updated"


def test_find_and_describe():
    g = graph._assemble(RESULTS)
    assert [n["id"] for n in graph.find(g, "p_status")] == ["field:100100100"]
    assert graph.find(g, "500")[0]["id"] == "rule:500"

    text = graph.describe(g, graph.find(g, "Set status")[0])
    assert "is triggered by (1): field P_SITE" in text
    assert "uses in code (2)" in text
    assert "Flagged invalid" in text


def test_the_agent_reads_a_cached_map(ov_home, tmp_path):
    seed_session(BASE_URL)
    data = {**graph._assemble(RESULTS), "instance": "acme", "host": "acme", "builtAt": 0}
    write_atomic(graph.graph_file("acme"), json.dumps(data))

    class Ctx:
        instance = "acme"
        work_dir = tmp_path
        cancel = None

    out = TOOLS_BY_NAME["ov_map"].handler({"object": "P_STATUS"}, Ctx())
    assert "is used in code by (1): rule Set status (500)" in out
    assert "is a field of (1): trackor_type Project (1)" in out


@pytest.mark.parametrize(
    ("before", "kind"),
    [
        ("  where config_field_id = ", "field"),
        ("  and prj.xitor_type_id = ", "trackor_type"),
        ("  where config_field_id in (100100100, ", "field"),
        ("  util.SetValByID(v_id, ", "field"),
        ("  v_rule_id number := ", "rule"),
        ("  c_kafka_notif_service_id constant notif_service.notif_service_id%type := ", None),
        ("  and status.value_number in (", None),
        ("  v := util.getval(:pk, ", None),
        ("  v := ", None),
        ("  x := 'xitor_type_id = ' || ", None),
    ],
)
def test_ids_link_only_with_context(before, kind):
    assert graph.id_kind(before) == kind


def test_ids_resolve_by_context_or_name_comment():
    g = graph._assemble(
        rows(
            fields=[{"CONFIG_FIELD_ID": "1000240", "CONFIG_FIELD_NAME": "P_STATUS"}],
            automations=[{"AUTOM_ID": "1000240", "AUTOM_NAME": "Lock"}],
            rules=[{"RULE_ID": "1", "RULE": "a"}, {"RULE_ID": "2", "RULE": "b"}],
            rule_code=[
                {
                    "RULE_ID": "1",
                    "CODE0": "c constant notif_service.notif_service_id%type := 1000240;",
                },
                {"RULE_ID": "2", "CODE0": "v := 1000240 /*P_STATUS*/; w := 1000240 -- Lock"},
            ],
        )
    )
    edges = {(e["source"], e["target"]) for e in g["edges"]}
    assert not any(s == "rule:1" for s, _ in edges)
    assert {("rule:2", "field:1000240"), ("rule:2", "automation:1000240")} <= edges
