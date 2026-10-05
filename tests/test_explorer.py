from __future__ import annotations

import re

import httpx
import pytest

from ov.agent import explorer

PACKAGE_BODY = "".join(f"-- line {i:05d}\n" for i in range(2500))


class FakeReader:
    def __init__(self, clobs: dict[str, str]) -> None:
        self.clobs = clobs
        self.queries: list[str] = []

    def page(self, sql: str, offset: int, size: int) -> list[dict[str, object]]:
        self.queries.append(sql)
        if "process" in sql:
            return [{"TS": "2026-10-01 10:00", "STATUS": "Error", "RUNTIME": 3, "MESSAGE": "ORA-1"}]
        row: dict[str, object] = {}
        for match in re.finditer(r"dbms_lob\.getlength\((\w+)\) n", sql):
            row["N"] = len(self.clobs.get(match.group(1), ""))
        for match in re.finditer(r"dbms_lob\.substr\((\w+), (\d+), (\d+)\) (c\d+)", sql):
            column, size_, start, alias = match.groups()
            text = self.clobs.get(column, "")
            row[alias.upper()] = text[int(start) - 1 : int(start) - 1 + int(size_)] or None
        return [row]


@pytest.fixture
def reader(monkeypatch):
    fake = FakeReader(
        {
            "db_package_body": PACKAGE_BODY,
            "db_package_spec": "package spec",
            "sql_text": "begin\n  select value into v from t where id = 4242;\nend;",
        }
    )
    monkeypatch.setattr(explorer, "_reader", lambda alias: fake)
    explorer.forget("acme")
    yield fake
    explorer.forget("acme")


def test_long_code_is_read_in_windows(reader):
    result = explorer.source("acme", "db_package:7")
    body, spec = result["sections"]
    assert (body["title"], spec["title"]) == ("Body", "Spec")
    assert body["code"] == PACKAGE_BODY
    assert spec["code"] == "package spec"
    windows = [q for q in reader.queries if "db_package_body" in q]
    assert len(windows) == -(-len(PACKAGE_BODY) // (explorer.CHUNK * explorer.CODE_CHUNKS))


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


def test_explorer_api(agent_server, reader):
    ok = httpx.get(f"{agent_server}/api/explorer/source", params={"instance": "acme", "id": "rule:1"})
    assert ok.status_code == 200
    assert ok.json()["sections"][0]["title"] == "Rule SQL"
    bad = httpx.get(f"{agent_server}/api/explorer/source", params={"instance": "acme", "id": "x"})
    assert bad.status_code == 400
    runs = httpx.get(f"{agent_server}/api/explorer/activity", params={"instance": "acme", "id": "rule:1"})
    assert runs.json()[0]["status"] == "Error"


@pytest.fixture
def agent_server(logged_in):
    import threading

    from ov.agent.server import AgentServer, Handler

    httpd = AgentServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
