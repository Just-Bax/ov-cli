from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest
from conftest import BASE_URL, seed_session

from ov.agent import db, skills, sources, state
from ov.agent.copilot import StreamResult
from ov.agent.ovproc import OvResult
from ov.agent.tools import ToolError, entity_link, run_ov_tool


@pytest.fixture(autouse=True)
def fresh_db(ov_home):
    db.close()
    yield
    db.close()


class FakeContext:
    def __init__(self, work_dir: Path, write: bool = False, approve: str = "Approve") -> None:
        from ov.agent.cancel import Cancel

        self.work_dir = work_dir
        self.cancel = Cancel()
        self.vision = True
        self.instance = "acme"
        self.opened: set[str] = set()
        self.events: list[dict] = []
        self.asked: list[str] = []
        self.write = write
        self.approve = approve

    def emit(self, event):
        self.events.append(event)

    def has_outcome(self):
        return False

    def ask_user(self, question, options, multiple, detail=None):
        self.asked.append(detail or question)
        return self.approve

    def require_login(self, host):
        return False

    def attach_image(self, name, url):
        pass

    def finish(self, outcome):
        pass

    def can_write(self):
        return self.write


def test_builtin_skills_ship_and_can_be_customized_and_reset():
    names = [s["name"] for s in skills.list_skills()]
    assert names[:3] == ["working-style", "ov-cli", "onevizion"]

    skills.update("ov-cli", {"content": "mine", "enabled": False})
    custom = next(s for s in skills.list_skills() if s["name"] == "ov-cli")
    assert custom["customized"] and not custom["enabled"] and custom["content"] == "mine"
    assert "ov-cli" not in [s["name"] for s in skills.enabled_skills()]

    skills.delete("ov-cli")
    reset = next(s for s in skills.list_skills() if s["name"] == "ov-cli")
    assert not reset["customized"] and reset["enabled"]


def test_user_skills_get_unique_names():
    first = skills.create("Case replies", "how to reply", "be short")
    second = skills.create("Case replies", "", "")
    assert (first, second) == ("case-replies", "case-replies-2")
    skills.delete(first)
    assert first not in [s["name"] for s in skills.list_skills()]


def test_folder_sources_are_searchable(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "notes.md").write_text("alpha\nRULE_ID beta\n", encoding="utf-8")

    sources.add("docs", "team notes", str(folder))
    assert sources.list_sources()[0]["ready"]
    assert "notes.md:2" in sources.search("docs", "RULE_ID")
    assert "2: RULE_ID beta" in sources.read("docs", "notes.md")
    with pytest.raises(ValueError):
        sources.read("docs", "../outside.txt")

    sources.remove("docs")
    assert folder.exists() and sources.list_sources() == []


def test_a_missing_folder_is_refused(tmp_path):
    with pytest.raises(sources.SourceError):
        sources.add("gone", "", str(tmp_path / "nope"))


def test_reducer_rewind_drops_later_items():
    s = state.empty_state({"id": "r1", "status": "queued"}, {"prompt": "hi"})
    events = [
        {"type": "user", "message": {"id": "u1", "role": "user", "text": "a", "ts": 1}},
        {"type": "text", "messageId": "a1", "delta": "he"},
        {"type": "text", "messageId": "a1", "delta": "llo"},
        {"type": "user", "message": {"id": "u2", "role": "user", "text": "b", "ts": 2}},
        {"type": "text", "messageId": "a2", "delta": "x"},
    ]
    for seq, event in enumerate(events):
        state.reduce(s, {"seq": seq, "ts": seq, "event": event})
    assert s["chat"][1]["text"] == "hello"

    state.reduce(s, {"seq": 9, "ts": 9, "event": {"type": "rewind", "itemId": "u2"}})
    assert [m["id"] for m in s["chat"]] == ["u1", "a1"]


def test_entity_links_use_admin_forms():
    assert entity_link("rule", "123", "acme.onevizion.com") == (
        "https://acme.onevizion.com/admin/rules/Form.do?id=123"
    )
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

    monkeypatch.setattr("ov.agent.tools.run_ov", fake_run)
    with pytest.raises(ToolError, match="write access is OFF"):
        run_ov_tool(["request", "DELETE", "/v3/users/1"], "acme", FakeContext(tmp_path))

    ctx = FakeContext(tmp_path, write=True)
    assert "Applied" in run_ov_tool(["request", "DELETE", "/v3/users/1"], "acme", ctx)
    assert calls[-2:] == [True, False]
    assert "DELETE /v3/users/1" in ctx.asked[0]

    with pytest.raises(ToolError, match="rejected"):
        run_ov_tool(
            ["request", "DELETE", "/v3/users/1"], "acme", FakeContext(tmp_path, True, "Reject")
        )


def test_a_run_streams_calls_tools_and_finishes(logged_in, monkeypatch):
    replies = iter(
        [
            StreamResult(
                text="Checking.",
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "ov", "arguments": '{"args": ["api", "tags"]}'},
                    }
                ],
            ),
            StreamResult(text="All good."),
        ]
    )

    def fake_chat(model, messages, tools, initiator, cancel, on_text):
        reply = next(replies)
        on_text(reply.text)
        return reply

    monkeypatch.setattr("ov.agent.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.copilot.supports_vision", lambda _: True)
    monkeypatch.setattr("ov.agent.tools.run_ov", lambda *a, **k: OvResult(0, "users\n", ""))

    from ov.agent.run import runs

    run = runs.create({"prompt": "what tags?", "instance": "acme"}, "test-model")
    for _ in range(100):
        if run.state["summary"]["status"] in ("done", "error"):
            break
        time.sleep(0.05)

    assert run.state["summary"]["status"] == "done", run.state.get("error")
    assert [t["status"] for t in run.state["tools"]] == ["ok"]
    assert run.state["chat"][-1]["text"] == "All good."
    assert db.list_runs()[0]["status"] == "done"
    runs.delete(run.id)


@pytest.fixture
def agent_server(logged_in):
    from ov.agent.server import AgentServer, Handler

    httpd = AgentServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_the_api_lists_instances_and_rejects_cross_site_posts(agent_server):
    seed_session(BASE_URL)
    rows = httpx.get(f"{agent_server}/api/instances").json()
    assert rows[0]["alias"] == "acme" and rows[0]["valid"]

    forged = httpx.post(
        f"{agent_server}/api/runs", content="{}", headers={"Content-Type": "text/plain"}
    )
    assert forged.status_code == 403
    foreign = httpx.post(
        f"{agent_server}/api/runs", json={}, headers={"Origin": "https://evil.test"}
    )
    assert foreign.status_code == 403


def test_uploads_round_trip(agent_server):
    response = httpx.post(
        f"{agent_server}/api/uploads",
        content=b"hello",
        headers={"Content-Type": "application/octet-stream", "X-File-Name": "a%20b.txt"},
    )
    saved = response.json()
    assert saved["name"] == "a b.txt"
    from ov.agent.workspace import uploads_dir

    assert (uploads_dir() / saved["id"]).read_bytes() == b"hello"


def test_settings_ignore_unknown_keys(agent_server):
    saved = httpx.put(
        f"{agent_server}/api/settings", json={"defaultModel": "m", "secret": "x"}
    ).json()
    assert saved["defaultModel"] == "m" and "secret" not in saved
    assert json.loads(json.dumps(saved))


def test_ov_tool_keeps_files_in_the_workspace(logged_in, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        "ov.agent.tools.run_ov", lambda args, **k: seen.append(args) or OvResult(0, "ok", "")
    )
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
    with pytest.raises(ToolError, match="sql tool"):
        run_ov_tool(["request", "POST", "/v3/sql/test", "-d", "delete from x"], "acme", ctx)


def test_dangling_tool_calls_get_stub_results():
    from ov.agent.run import _answered

    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "ok"},
    ]
    fixed = _answered(messages)
    assert [m.get("tool_call_id") for m in fixed[2:]] == ["a", "b"]


def test_a_restart_marks_running_runs_interrupted(ov_home):
    db.create_run("rabc", "t", "m", {"prompt": "x"})
    db.update_run("rabc", status="running")
    db.append_event("rabc", 0, {"type": "status", "status": "running"})
    db.close()

    assert db.list_runs()[0]["status"] == "error"
    assert db.load_events("rabc")[-1]["event"]["status"] == "error"


def test_attachments_that_could_run_script_are_downloaded(agent_server, monkeypatch):
    from ov.agent.run import runs
    from ov.agent.workspace import attachments_dir

    monkeypatch.setattr("ov.agent.run.Run.begin", lambda self, data: None)
    run = runs.create({"prompt": "x"}, "m")
    (attachments_dir(run.id) / "page.html").write_text("<script>1</script>")
    (attachments_dir(run.id) / "shot.png").write_bytes(b"png")

    html = httpx.get(f"{agent_server}/api/runs/{run.id}/files/page.html")
    assert html.headers["content-disposition"].startswith("attachment")
    assert html.headers["content-type"] == "application/octet-stream"
    png = httpx.get(f"{agent_server}/api/runs/{run.id}/files/shot.png")
    assert png.headers["content-disposition"].startswith("inline")
    assert png.headers["content-security-policy"] == "sandbox"
    runs.delete(run.id)


def test_a_local_page_on_another_port_is_refused(agent_server):
    other = httpx.get(f"{agent_server}/api/runs", headers={"Origin": "http://127.0.0.1:3000"})
    assert other.status_code == 403
