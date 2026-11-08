from __future__ import annotations

import json

import pytest
from helpers.sessions import BASE_URL, seed_session

from ov.agent.instances import graph, linking
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
    data = {
        **graph._assemble(RESULTS),
        "instance": "acme",
        "host": "acme",
        "builtAt": 0,
        "source": "export",
        "warnings": [],
    }
    write_atomic(graph.graph_file("acme"), json.dumps(data))

    class Ctx:
        instance = "acme"
        work_dir = tmp_path
        cancel = None

    out = TOOLS_BY_NAME["ov_map"].handler({"object": "P_STATUS"}, Ctx())
    assert "is used in code by (1): rule Set status (500)" in out
    assert "is a field of (1): trackor_type Project (1)" in out
    assert "changes made by others since then are not detected" in out


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
    assert linking.id_kind(before) == kind


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


@pytest.mark.parametrize(("versioned", "expected"), [(1, "t.is_current_version = 1"), (0, "1 = 1")])
def test_workflow_queries_follow_the_instance_schema(monkeypatch, versioned, expected):
    seen: list[str] = []

    class Reader:
        alias = "acme"

        def page(self, sql, offset, size):
            seen.append(sql)
            return [{"N": versioned}]

        def rows(self, sql, size):
            seen.append(sql)
            return []

    monkeypatch.setattr(graph, "EXPORTS", {})
    graph._read(Reader(), list(graph.QUERIES), lambda _: None)

    workflow_sql = [q for q in seen if "from wf_template" in q]
    assert len(workflow_sql) == 2 and all(expected in q and "{current}" not in q for q in workflow_sql)


class ChangeLogReader:
    alias = "acme"

    def __init__(self, tables):
        self.tables = tables
        self.stamps = {str(component): "1@2026-11-01 10:00:00.0" for component in graph.CHANGE_SOURCES}
        self.read: list[str] = []

    def page(self, sql, offset, size):
        if sql == graph.FINGERPRINT_SQL:
            return [
                {"COMPONENT_ID": c, "N": stamp.split("@")[0], "CHANGED": stamp.split("@")[1]}
                for c, stamp in self.stamps.items()
            ]
        return [{"N": 1}]

    def rows(self, sql, size):
        name = next(n for n in graph.QUERIES if sql == graph.QUERIES[n].replace("{current}", graph.CURRENT_VERSION))
        self.read.append(name)
        return self.tables.get(name, [])


@pytest.fixture
def change_log(ov_home, monkeypatch):
    seed_session(BASE_URL)
    reader = ChangeLogReader(dict(RESULTS))
    monkeypatch.setattr(graph, "SqlReader", lambda alias, cancel: reader)
    monkeypatch.setattr(graph, "EXPORTS", {"package_code": lambda sql: reader.tables["package_code"]})
    monkeypatch.setattr(graph.access, "ensure", lambda alias: {"testSql": True, "export": True})
    monkeypatch.setattr(graph, "_checked_at", {})
    monkeypatch.setattr(graph, "_written", set())
    return reader


def test_a_map_is_rechecked_only_once_the_recheck_interval_passed(change_log):
    built = graph.build("acme")
    change_log.read.clear()

    assert graph.sync("acme") == built
    assert change_log.read == []


def test_a_changed_component_rereads_only_its_own_sources(change_log, monkeypatch):
    built = graph.build("acme")
    change_log.read.clear()
    monkeypatch.setattr(graph, "RECHECK_SECONDS", 0)
    change_log.stamps["4"] = "2@2026-11-08 09:00:00.0"
    change_log.tables["rules"] = [*RESULTS["rules"], {"RULE_ID": "501", "RULE": "Added by someone"}]

    synced = graph.sync("acme")

    assert sorted(change_log.read) == ["invalid", "rule_bindings", "rule_code", "rules"]
    assert synced["refreshed"] == ["rules"]
    assert "rule:501" in {n["id"] for n in synced["nodes"]}
    assert synced["fingerprint"]["4"] == "2@2026-11-08 09:00:00.0"
    assert len(synced["nodes"]) == len(built["nodes"]) + 1


def test_an_unchanged_change_log_keeps_the_map(change_log, monkeypatch):
    built = graph.build("acme")
    change_log.read.clear()
    monkeypatch.setattr(graph, "RECHECK_SECONDS", 0)

    assert graph.sync("acme") == built
    assert change_log.read == []


def test_a_write_by_the_agent_rechecks_before_the_interval(change_log):
    graph.build("acme")
    change_log.read.clear()
    change_log.stamps["5"] = "2@2026-11-08 09:00:00.0"

    graph.note_write("acme")
    synced = graph.sync("acme")

    assert synced["refreshed"] == ["fields"]
    assert sorted(change_log.read) == ["fields", "invalid"]


def test_a_map_without_its_sources_is_built_again(change_log, monkeypatch):
    graph.build("acme")
    graph.sources_file("acme").unlink()
    change_log.read.clear()
    monkeypatch.setattr(graph, "RECHECK_SECONDS", 0)

    graph.sync("acme")

    assert sorted(change_log.read) == sorted(graph.QUERIES)


def test_a_map_saved_in_an_older_shape_counts_as_missing(ov_home):
    seed_session(BASE_URL)
    write_atomic(graph.graph_file("acme"), json.dumps({**graph._assemble(RESULTS), "builtAt": 0, "warnings": []}))

    assert graph.load("acme") is None
    assert graph.status("acme") == {"state": "none"}
