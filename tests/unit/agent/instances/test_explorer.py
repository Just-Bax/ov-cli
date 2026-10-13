from __future__ import annotations

import pytest
from helpers.fake_reader import PACKAGE_BODY, install_fake_reader

from ov.agent.instances import explorer
from ov.agent.instances.ovproc import OvResult


@pytest.fixture
def reader(monkeypatch):
    yield from install_fake_reader(monkeypatch)


def test_packages_are_read_with_one_component_export(reader, monkeypatch):
    seen = []
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><COMPONENTS><DB_PACKAGES><DB_PACKAGES_ITEM>'
        "<DB_PACKAGE_ID>7</DB_PACKAGE_ID><DB_PACKAGE_SPEC>package spec</DB_PACKAGE_SPEC>"
        f"<DB_PACKAGE_BODY>{PACKAGE_BODY}</DB_PACKAGE_BODY><BPD_ITEMS/></DB_PACKAGES_ITEM></DB_PACKAGES></COMPONENTS>"
    )

    def fake_run(args, **_):
        seen.append(args)
        return OvResult(0, xml, "")

    monkeypatch.setattr("ov.agent.instances.components.run_ov", fake_run)
    body, spec = explorer.source("acme", "db_package:7")["sections"]
    assert (body["title"], body["code"], spec["code"]) == ("Body", PACKAGE_BODY, "package spec")
    assert len(seen) == 1 and '"component_ids": [7]' in seen[0][seen[0].index("-d") + 1]
    assert not reader.queries


def test_source_is_cached_until_forgotten(reader):
    explorer.source("acme", "rule:1")
    count = len(reader.queries)
    explorer.source("acme", "rule:1")
    assert len(reader.queries) == count
    explorer.forget("acme")
    explorer.source("acme", "rule:1")
    assert len(reader.queries) > count


def test_rule_source_carries_hints(reader):
    (section,) = explorer.source("acme", "rule:1")["sections"]
    titles = {h["title"] for h in section["hints"]}
    assert "SELECT INTO can fail with no data" in titles
    assert "Hard-coded value" in titles


def test_bad_ids_are_rejected():
    with pytest.raises(explorer.ExplorerError):
        explorer.source("acme", "rule:abc")
    assert explorer.activity("acme", "trackor_type:1") == []


def test_activity_rows(reader):
    (run,) = explorer.activity("acme", "rule:1")
    assert run == {"ts": "2026-10-01 10:00", "status": "Error", "runtime": 3, "message": "ORA-1"}


def hint_titles(code: str, node: dict | None = None, known: set[int] | None = None) -> list[str]:
    return [h["title"] for h in explorer.hints(code, node or {"type": "rule"}, known)]


def test_hints_flag_risky_code():
    code = "\n".join(
        [
            "begin",
            "  for a in (select * from x) loop",
            "    for b in (select id from y) loop",
            "      v := util.getvalnumbyid(b.id, 'F');",
            "    end loop;",
            "  end loop;",
            "  commit;",
            "exception when others then null;",
            "end;",
        ]
    )
    titles = hint_titles(code)
    for title in [
        "Nested loops",
        "Query inside a loop",
        "SELECT *",
        "COMMIT or ROLLBACK in a rule",
        "Errors are silently ignored",
    ]:
        assert title in titles


def test_hints_skip_known_ids_and_safe_select_into():
    code = "begin\n  select max(v) into x from t where config_field_id = 1001;\nend;"
    assert hint_titles(code, known={1001}) == []
    assert "Hard-coded value" in hint_titles(code)


def test_rule_trigger_hints():
    node = {"type": "rule", "trigger": "Trackor Updated", "async": False}
    assert "Runs on every update" in hint_titles("null;", node)
    assert "Runs on every update" not in hint_titles("null;", {**node, "filtered": True})
    long_code = "null;\n" * (explorer.LONG_SYNC_LINES + 1)
    assert "Long rule runs while the user waits" in hint_titles(long_code, node)
    assert "Long rule runs while the user waits" not in hint_titles(long_code, {**node, "async": True})
