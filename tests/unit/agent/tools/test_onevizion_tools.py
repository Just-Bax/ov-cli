from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.agent import FakeContext

from ov.agent.instances.ovproc import OvResult
from ov.agent.tools.base import ToolError
from ov.agent.tools.onevizion import entity_link, run_ov_tool


def test_entity_links_use_admin_forms():
    assert entity_link("rule", "123", "acme.onevizion.com") == ("https://acme.onevizion.com/admin/rules/Form.do?id=123")
    assert entity_link("field", "123", "acme") is None


def test_ov_tool_refuses_session_commands(logged_in, tmp_path):
    with pytest.raises(ToolError, match="not allowed"):
        run_ov_tool(["logout"], "acme", FakeContext(tmp_path))


def test_a_blocked_write_needs_access_then_approval(logged_in, tmp_path, monkeypatch):
    calls = []

    def fake_run(args, timeout=0, read_only=True, cancel=None, cwd=None):
        calls.append(read_only)
        if read_only:
            return OvResult(7, "", "Read-only mode (OV_READONLY) blocks DELETE")
        return OvResult(0, "deleted", "")

    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", fake_run)
    with pytest.raises(ToolError, match="write access is OFF"):
        run_ov_tool(["request", "DELETE", "/v3/users/1"], "acme", FakeContext(tmp_path))

    ctx = FakeContext(tmp_path, write=True)
    assert "Applied" in run_ov_tool(["request", "DELETE", "/v3/users/1"], "acme", ctx)
    assert calls[-2:] == [True, False]
    assert "DELETE /v3/users/1" in ctx.asked[0]

    with pytest.raises(ToolError, match="rejected"):
        run_ov_tool(["request", "DELETE", "/v3/users/1"], "acme", FakeContext(tmp_path, True, "Reject"))


def test_ov_tool_keeps_files_in_the_workspace(logged_in, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda args, **k: seen.append(args) or OvResult(0, "ok", ""))
    ctx = FakeContext(tmp_path)
    run_ov_tool(["request", "GET", "/x", "--out=C:/evil/a.bin"], "acme", ctx)
    run_ov_tool(["request", "POST", "/x", "-d", "@~/.ov/credentials.json"], "acme", ctx)
    run_ov_tool(["request", "POST", "/x", "--file", "f=/etc/passwd"], "acme", ctx)

    assert seen[0][-1] == str(tmp_path / "a.bin")
    assert seen[1][-1] == "@" + str(tmp_path / "credentials.json")
    assert seen[2][-1] == "f=@" + str(tmp_path / "passwd")


def test_ov_tool_rejects_option_first_and_raw_sql(logged_in, tmp_path):
    ctx = FakeContext(tmp_path)
    for args in (["-ixyz", "logout"], ["--instance=x", "api", "tags"], ["api", "tags", "-iabc"]):
        with pytest.raises(ToolError):
            run_ov_tool(args, "acme", ctx)
    with pytest.raises(ToolError, match="ov_sql tool"):
        run_ov_tool(["request", "POST", "/v3/sql/test", "-d", "delete from x"], "acme", ctx)


def test_components_are_exported_to_workspace_files(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools import tool_named

    body = "\n".join(f"line {i}" for i in range(12000))
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><COMPONENTS><DB_PACKAGES><DB_PACKAGES_ITEM>'
        f"<DB_PKG_NAME>PKG_BIG</DB_PKG_NAME><DB_PACKAGE_BODY>{body}</DB_PACKAGE_BODY>"
        "<DB_PACKAGE_ID>12</DB_PACKAGE_ID><BPD_ITEMS/></DB_PACKAGES_ITEM></DB_PACKAGES></COMPONENTS>"
    )
    seen: list[list[str]] = []

    def fake(args, **_):
        seen.append(args)
        Path(args[args.index("--out") + 1]).write_text(xml, encoding="utf-8")
        return OvResult(0, "{}", "")

    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", fake)
    text = tool_named("ov_export").handler({"component_type": "db_package", "ids": [12]}, FakeContext(tmp_path))

    assert "DB_PKG_NAME: PKG_BIG" in text
    assert "DB_PACKAGE_BODY: 12000 lines in db_package-12-db_package_body.txt" in text
    assert (tmp_path / "db_package-12-db_package_body.txt").read_text(encoding="utf-8") == body
    assert seen[0][2:5] == ["request", "POST", "/v3/components/exports/run"]
    with pytest.raises(ToolError, match="1 to 20"):
        tool_named("ov_export").handler({"component_type": "RULE", "ids": list(range(21))}, FakeContext(tmp_path))


def test_sql_results_mask_secrets_without_refusing_the_query(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools import tool_named

    body = {
        "status": "SUCCESS",
        "columns": ["NAME", "VALUE", "API_TOKEN", "MODULE_ID"],
        "rows": [
            {"cells": ["kafkaPassword", "hunter2", "abc", 12]},
            {"cells": ["batchSize", "500", "def", 12]},
            {"cells": ["settings", '{"url": "x", "client_secret": "s3"}', None, 13]},
        ],
    }
    big = json.dumps(body) + " " * 30_000
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(0, big, ""))
    out = tool_named("ov_sql").handler(
        {"query": "select name, value from module_param where name not like '%PASS%'"}, FakeContext(tmp_path)
    )
    lines = out.splitlines()
    assert lines[2] == "kafkaPassword\t***\t***\t12"
    assert lines[3] == "batchSize\t500\t***\t12"
    assert '"client_secret": "***"' in lines[4] and '"url": "x"' in lines[4]
    assert "[took " in out


def test_sql_timeout_explains_what_to_do(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools import tool_named

    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(1, "", "", timed_out=True))
    with pytest.raises(ToolError, match="may still be running"):
        tool_named("ov_sql").handler({"query": "select 1 from dual", "timeout": 30}, FakeContext(tmp_path))
