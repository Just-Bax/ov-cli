from __future__ import annotations

import io
import zipfile

import pytest
from helpers.agent import FakeContext

from ov.agent.instances import access
from ov.agent.tools import ddl, mcp, tool_specs
from ov.agent.tools.base import ToolError

TOOLS = {
    "tools": [
        {
            "name": "trackors_search",
            "description": "Searches trackors.",
            "inputSchema": {"properties": {"trackor_type": {}}},
        }
    ]
}


class Response:
    def __init__(self, body=None, content: bytes = b"") -> None:
        self.body = body
        self.content = content

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, calls: list) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post_json(self, path, message):
        self.calls.append((path, message["method"], message["params"]))
        if message["method"] == "tools/list":
            return Response({"jsonrpc": "2.0", "id": message["id"], "result": TOOLS})
        return Response(
            {"jsonrpc": "2.0", "id": message["id"], "result": {"content": [{"type": "text", "text": "2 found"}]}}
        )

    def api(self, method, path, accept=""):
        self.calls.append((method, path))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("util_spec.sql", "CREATE OR REPLACE PACKAGE UTIL AS\n  procedure SetValNumByID;\nEND;")
            zipped.writestr("xitor.sql", "CREATE TABLE XITOR (XITOR_ID NUMBER);")
        return Response(content=archive.getvalue())


@pytest.fixture
def calls(logged_in, monkeypatch):
    seen: list = []
    monkeypatch.setattr(mcp, "open_client", lambda alias: FakeClient(seen))
    monkeypatch.setattr(ddl, "open_client", lambda alias: FakeClient(seen))
    return seen


def _allow(monkeypatch, **granted):
    monkeypatch.setattr(access, "allows", lambda alias, capability: granted.get(capability, False))


def test_mcp_lists_and_calls_tools(calls, tmp_path, monkeypatch):
    _allow(monkeypatch, mcp=True)
    ctx = FakeContext(tmp_path)

    listed = mcp.TOOLS[0].handler({}, ctx)
    called = mcp.TOOLS[0].handler({"tool": "trackors_search", "arguments": {"trackor_type": "Site"}}, ctx)

    assert "- trackors_search(trackor_type): Searches trackors." in listed
    assert called == "2 found"
    assert calls[-1] == ("/ai/mcp", "tools/call", {"name": "trackors_search", "arguments": {"trackor_type": "Site"}})


def test_mcp_writes_wait_for_approval(calls, tmp_path, monkeypatch):
    _allow(monkeypatch, mcp=True)
    with pytest.raises(ToolError, match="Read-only"):
        mcp.TOOLS[0].handler({"tool": "trackor_update"}, FakeContext(tmp_path))
    ctx = FakeContext(tmp_path, write=True)
    assert mcp.TOOLS[0].handler({"tool": "trackor_update", "arguments": {"id": 1}}, ctx) == "2 found"
    assert '"id": 1' in ctx.asked[0]


@pytest.mark.parametrize("name", ["trackor_assign", "chats_messages_create_by_trackor_id", "list_and_delete"])
def test_an_mcp_tool_that_is_not_plainly_a_read_needs_approval(calls, tmp_path, monkeypatch, name):
    _allow(monkeypatch, mcp=True)
    with pytest.raises(ToolError, match="Read-only"):
        mcp.TOOLS[0].handler({"tool": name}, FakeContext(tmp_path))


def test_mcp_explains_a_missing_privilege(calls, tmp_path, monkeypatch):
    _allow(monkeypatch)
    with pytest.raises(ToolError, match="MCP_SERVER privilege"):
        mcp.TOOLS[0].handler({}, FakeContext(tmp_path))


def test_the_platform_source_is_read_by_name_and_searched(calls, tmp_path, monkeypatch):
    _allow(monkeypatch, dbSource=True)
    ctx = FakeContext(tmp_path)

    spec = ddl.TOOLS[0].handler({"name": "util", "kind": "package_spec"}, ctx)
    found = ddl.TOOLS[0].handler({"find": "setvalnumbyid"}, ctx)

    assert spec.startswith("-- package_specs/util_spec.sql\nCREATE OR REPLACE PACKAGE UTIL")
    assert "package_specs/util_spec.sql:2: procedure SetValNumByID;" in found
    downloads = [c for c in calls if c[0] == "GET"]
    assert len(downloads) == len(ddl.GROUPS)


def test_ai_enabled_tools_are_offered_only_where_allowed(logged_in, monkeypatch):
    names = lambda: {spec["function"]["name"] for spec in tool_specs()}  # noqa: E731
    assert "ov_mcp" not in names() and "ov_ddl" not in names()
    _allow(monkeypatch, mcp=True, dbSource=True)
    assert {"ov_mcp", "ov_ddl"} <= names()
