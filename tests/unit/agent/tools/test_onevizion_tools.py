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
    with pytest.raises(ToolError, match="this thread is Read-only"):
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


def test_a_token_field_name_does_not_hide_the_rule_beside_it(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools import tool_named

    body = {
        "status": "SUCCESS",
        "columns": ["RULE_ID", "RULE_NAME", "FIELD_NAME"],
        "rows": [{"cells": ["100026670", "UDL Trigger Token", "C_GENERATE_TOKEN"]}],
    }

    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(0, json.dumps(body), ""))
    out = tool_named("ov_sql").handler({"query": "select rule_id from rule"}, FakeContext(tmp_path))
    assert out.splitlines()[2] == "100026670\tUDL Trigger Token\tC_GENERATE_TOKEN"


def test_the_generic_sql_error_gets_a_hint(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools import tool_named

    failed = json.dumps({"status": "FAILED", "error_message": "Error[9478]: Unexpected error"})
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(0, failed, ""))
    with pytest.raises(ToolError, match="Name the columns you need"):
        tool_named("ov_sql").handler({"query": "select * from rule"}, FakeContext(tmp_path))


def test_a_missing_instance_is_asked_for(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools.onevizion import _target

    ctx = FakeContext(tmp_path, approve="acme")
    ctx.instance = ""
    assert _target(None, ctx) == "acme"
    assert ctx.asked == ["Which instance should I use?"]


def test_sql_timeout_reports_the_limit_and_the_measured_time(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools import tool_named

    clock = iter([0.0, 300.4])
    monkeypatch.setattr("ov.agent.tools.onevizion.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(5, "", "timed out"))
    with pytest.raises(ToolError, match=r"no answer on acme in 300s \(ran 300\.4s\).*may still be running"):
        tool_named("ov_sql").handler({"query": "select 1 from dual"}, FakeContext(tmp_path))


def test_sql_errors_before_the_limit_keep_their_own_message(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools import tool_named

    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", lambda *a, **k: OvResult(5, "", "ORA-00942"))
    with pytest.raises(ToolError, match="ORA-00942"):
        tool_named("ov_sql").handler({"query": "select 1 from dual"}, FakeContext(tmp_path))


def test_the_ov_subprocess_gets_the_call_timeout_and_a_grace_period(monkeypatch):
    from ov.agent.instances import ovproc

    seen = {}

    class FakeProcess:
        returncode = 0

    def fake_popen(args, env, **_):
        seen["env"] = env
        return FakeProcess()

    def fake_wait(process, timeout, cancel, held):
        seen["limit"] = timeout
        return False

    monkeypatch.setattr(ovproc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ovproc, "_wait", fake_wait)
    ovproc.run_ov(["sql"], timeout=300)
    assert seen["env"]["OV_TIMEOUT_SECONDS"] == "300"
    assert seen["limit"] == 300 + ovproc.TIMEOUT_GRACE_SECONDS


IMPORT_RESULT = json.dumps(
    [
        {
            "component_type": "RULE",
            "id": 7,
            "component": "Push to Kafka",
            "status": "UPDATED",
            "messages": [{"status": "WARNING", "message": "Trigger changed"}],
        }
    ]
)


def test_imports_dry_run_first_and_need_approval_to_apply(logged_in, tmp_path, monkeypatch):
    from ov.agent.tools import tool_named
    from ov.core.errors import EXIT_READ_ONLY

    (tmp_path / "export-1.xml").write_text("<COMPONENTS/>", encoding="utf-8")
    seen: list[tuple[list[str], bool]] = []

    def fake(args, read_only=True, **_):
        seen.append((args, read_only))
        dry = "is_dry_run=true" in args
        if read_only and not dry:
            return OvResult(EXIT_READ_ONLY, "", "Read-only mode")
        return OvResult(0, IMPORT_RESULT, "")

    monkeypatch.setattr("ov.agent.tools.onevizion.run_ov", fake)
    picked = [{"component_type": "rule", "mode": "update_if_exist", "ids": [7]}]
    tool = tool_named("ov_import")

    text = tool.handler({"file": "export-1.xml", "components": picked}, FakeContext(tmp_path))
    assert text.startswith("Dry run, nothing changed:") and "RULE Push to Kafka: UPDATED" in text
    assert "WARNING: Trigger changed" in text
    args = seen[0][0]
    assert args[args.index("--file") + 1] == f"file=@{tmp_path / 'export-1.xml'}"
    assert json.loads(args[args.index("--field") + 1].removeprefix("components:=")) == [
        {"component_type": "RULE", "mode": "UPDATE_IF_EXIST", "components": [{"id": 7}]}
    ]

    with pytest.raises(ToolError, match="this thread is Read-only"):
        tool.handler({"file": "export-1.xml", "dry_run": False}, FakeContext(tmp_path))
    ctx = FakeContext(tmp_path, write=True)
    assert tool.handler({"file": "export-1.xml", "dry_run": False}, ctx).startswith("Imported:")
    assert "is_import_all=true" in seen[-1][0] and seen[-1][1] is False and ctx.asked


def test_imports_check_the_file_and_component_types(logged_in, tmp_path):
    from ov.agent.tools import tool_named

    tool = tool_named("ov_import")
    with pytest.raises(ToolError, match=r"No file missing\.xml"):
        tool.handler({"file": "missing.xml"}, FakeContext(tmp_path))
    (tmp_path / "x.xml").write_text("<COMPONENTS/>", encoding="utf-8")
    with pytest.raises(ToolError, match="Unknown import mode"):
        tool.handler(
            {"file": "x.xml", "components": [{"component_type": "RULE", "mode": "NOPE"}]}, FakeContext(tmp_path)
        )
