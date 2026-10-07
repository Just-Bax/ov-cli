from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest
from conftest import BASE_URL, seed_session

from ov.agent import db, skills, state
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
        self.edits: list[tuple] = []
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

    def record_edit(self, path, before, after, created):
        self.edits.append((path, before, after, created))

    def finish(self, outcome):
        pass

    def can_write(self):
        return self.write


def test_builtin_skills_ship_and_can_be_customized_and_reset():
    names = [s["name"] for s in skills.list_skills()]
    assert names[:7] == [
        "onevizion",
        "working-style",
        "ov-cli",
        "workspace",
        "datadog",
        "pagerduty",
        "tce-best-practices",
    ]

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


@pytest.fixture
def workspace(tmp_path):
    folder = tmp_path / "code"
    (folder / "module" / "node_modules").mkdir(parents=True)
    (folder / "module" / "main.py").write_text("alpha\nRULE_ID = 1\n", encoding="utf-8")
    (folder / "module" / "node_modules" / "skip.js").write_text("RULE_ID", encoding="utf-8")
    db.save_settings({"workspace": str(folder)})
    yield folder
    db.save_settings({"workspace": ""})


def test_the_workspace_reads_searches_and_edits_inside_its_folder(workspace, tmp_path):
    from ov.agent import project

    assert "module/" in project.listing("", "")
    assert project.listing("", "*.py") == "module/main.py"
    assert project.search("RULE_ID", "", "", False).startswith("module/main.py:2:")
    assert "2: RULE_ID = 1" in project.read("module/main.py", 1, None)

    assert project.edit("module/main.py", "RULE_ID = 1", "RULE_ID = 2", False).startswith("Edited")
    assert "RULE_ID = 2" in project.text_of("module/main.py")
    project.write("module/new/readme.md", "hi")
    assert (workspace / "module" / "new" / "readme.md").read_text(encoding="utf-8") == "hi"

    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    for outside in ("../secret.txt", str(tmp_path / "secret.txt")):
        with pytest.raises(project.ProjectError, match="outside the workspace"):
            project.read(outside, 1, None)


def test_risky_commands_need_approval(workspace, tmp_path):
    from ov.agent import project

    base = project.root()
    assert project.risks("git status && pytest tests/x.py", base) == []
    assert project.risks("git push origin main", base) == ["pushes to a remote"]
    assert project.risks("Remove-Item -Recurse build", base) == ["deletes files"]
    assert project.risks("gh pr view 12 --comments && gh pr diff 12", base) == []
    assert project.risks("gh pr comment 12 -b ok", base) == ["changes something on GitHub"]
    assert project.risks("gh api repos/a/b/pulls/1/comments", base) == []
    assert project.risks("gh api -X POST repos/a/b/issues/1/comments -f body=x", base) == [
        "changes something on GitHub"
    ]
    assert project.risks(f"type {tmp_path / 'secret.txt'}", base)[0].startswith("touches")
    assert project.risks(f"type {workspace / 'module' / 'main.py'}", base) == []


def test_ws_run_asks_before_risky_commands(workspace, tmp_path):
    from ov.agent.tools import ToolError, tool_named

    ctx = FakeContext(tmp_path, approve="Reject")
    tool = tool_named("ws_run")
    assert "hello" in tool.handler({"command": "echo hello", "cwd": "module"}, ctx)
    assert ctx.asked == []
    with pytest.raises(ToolError, match="rejected"):
        tool.handler({"command": "git push"}, ctx)
    assert ctx.asked == ["the workspace root> git push"]


def test_workspace_tools_are_offered_only_with_a_folder(tmp_path):
    from ov.agent.tools import tool_specs

    assert "ws_run" not in {s["function"]["name"] for s in tool_specs()}
    db.save_settings({"workspace": str(tmp_path)})
    assert "ws_run" in {s["function"]["name"] for s in tool_specs()}
    with pytest.raises(ValueError):
        db.save_settings({"workspace": str(tmp_path / "missing")})
    db.save_settings({"workspace": ""})


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

    monkeypatch.setattr("ov.agent.tools.run_ov", fake_run)
    with pytest.raises(ToolError, match="write access is OFF"):
        run_ov_tool(["request", "DELETE", "/v3/users/1"], "acme", FakeContext(tmp_path))

    ctx = FakeContext(tmp_path, write=True)
    assert "Applied" in run_ov_tool(["request", "DELETE", "/v3/users/1"], "acme", ctx)
    assert calls[-2:] == [True, False]
    assert "DELETE /v3/users/1" in ctx.asked[0]

    with pytest.raises(ToolError, match="rejected"):
        run_ov_tool(["request", "DELETE", "/v3/users/1"], "acme", FakeContext(tmp_path, True, "Reject"))


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

    def fake_chat(*args, cancel, on_text):
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

    forged = httpx.post(f"{agent_server}/api/runs", content="{}", headers={"Content-Type": "text/plain"})
    assert forged.status_code == 403
    foreign = httpx.post(f"{agent_server}/api/runs", json={}, headers={"Origin": "https://evil.test"})
    assert foreign.status_code == 403


def test_uploads_round_trip(agent_server):
    response = httpx.post(
        f"{agent_server}/api/uploads",
        content=b"hello",
        headers={"Content-Type": "application/octet-stream", "X-File-Name": "a%20b.txt"},
    )
    saved = response.json()
    assert saved["name"] == "a b.txt"
    from ov.agent.runfiles import uploads_dir

    assert (uploads_dir() / saved["id"]).read_bytes() == b"hello"


def test_settings_ignore_unknown_keys(agent_server):
    saved = httpx.put(f"{agent_server}/api/settings", json={"defaultModel": "m", "secret": "x"}).json()
    assert saved["defaultModel"] == "m" and "secret" not in saved
    assert json.loads(json.dumps(saved))


def test_ov_tool_keeps_files_in_the_workspace(logged_in, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("ov.agent.tools.run_ov", lambda args, **k: seen.append(args) or OvResult(0, "ok", ""))
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
    from ov.agent.runfiles import attachments_dir

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


def test_a_local_page_on_another_port_is_refused(agent_server):
    other = httpx.get(f"{agent_server}/api/runs", headers={"Origin": "http://127.0.0.1:3000"})
    assert other.status_code == 403


def test_a_bare_case_number_or_link_is_a_case():
    from ov.agent.cases import case_ref

    assert case_ref("193915") == "193915"
    assert case_ref(" Case #193915 ") == "193915"
    link = "https://trackor.onevizion.com/form/ConfigAppForm.do?id=100124829949"
    assert case_ref(link) == link
    assert case_ref("why does case 193915 fail?") is None


def test_finish_keeps_existing_matches_and_the_reply(tmp_path):
    from ov.agent.tools import TOOLS_BY_NAME

    ctx = FakeContext(tmp_path)
    outcomes = []
    ctx.finish = outcomes.append
    TOOLS_BY_NAME["run_report"].handler(
        {
            "findings": [{"title": "t", "verdict": "fix", "summary": "s", "evidence": ["e"]}],
            "existing": [{"key": "IT-1", "title": "x", "covers": "partly"}],
            "reply": "Yes, fixed.",
            "time_saved_minutes": 30,
            "time_saved_basis": "b",
        },
        ctx,
    )
    assert outcomes[0]["existing"] == [{"key": "IT-1", "title": "x", "covers": "partly"}]
    assert outcomes[0]["reply"] == "Yes, fixed."


def test_a_run_can_be_renamed(agent_server, monkeypatch):
    from ov.agent.run import runs

    monkeypatch.setattr("ov.agent.run.Run.begin", lambda self, data: None)
    run = runs.create({"prompt": "x"}, "m")
    ok = httpx.post(f"{agent_server}/api/runs/{run.id}/title", json={"title": "  NORAD   report "})
    assert ok.status_code == 200
    assert db.list_runs()[0]["title"] == "NORAD report"
    blank = httpx.post(f"{agent_server}/api/runs/{run.id}/title", json={"title": " "})
    assert blank.status_code == 400


def test_boolean_settings_are_stored_as_booleans():
    saved = db.save_settings({"notify": 1, "showTimeSaved": "", "expandTools": True})
    assert saved["notify"] is True and saved["showTimeSaved"] is False and saved["expandTools"]
    assert db.get_settings()["maxSteps"] == 80


def test_instance_sign_in_keeps_the_url_and_tenant(agent_server, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr("ov.agent.ovproc.run_ov", lambda args, **k: seen.append(args) or OvResult(0, "ok", ""))
    url = "http://portal.customer.example:8443/ov"
    res = httpx.post(f"{agent_server}/api/instances/login", json={"url": url, "tenant": "North"})
    assert res.json()["ok"]
    assert seen[-1][:2] == ["login", url]
    assert seen[-1][-2:] == ["--tenant", "North"]

    httpx.post(f"{agent_server}/api/instances/login", json={"url": url})
    assert "--tenant" not in seen[-1]


def test_instance_sign_in_passes_a_token_on_stdin(agent_server, monkeypatch):
    seen: list[tuple[list[str], str | None]] = []

    def fake(args, **kwargs):
        seen.append((args, kwargs.get("stdin")))
        return OvResult(0, "ok", "")

    monkeypatch.setattr("ov.agent.ovproc.run_ov", fake)
    url = "https://acme.onevizion.test"
    res = httpx.post(f"{agent_server}/api/instances/login", json={"url": url, "token": "K:S"})
    assert res.json()["ok"]
    assert seen[-1] == (["login", url, "--keep-current", "--timeout", "280", "--token", "-"], "K:S")
    both = httpx.post(f"{agent_server}/api/instances/login", json={"url": url, "token": "K:S", "tenant": "x"})
    assert both.status_code == 400


def test_an_instance_can_be_removed(agent_server, monkeypatch):
    seed_session(BASE_URL)
    seen: list[list[str]] = []

    def fake(args, **kwargs):
        seen.append(args)
        assert kwargs.get("read_only") is False
        from ov import session as session_store

        session_store.remove(args[1])
        return OvResult(0, "{}", "")

    monkeypatch.setattr("ov.agent.server.run_ov", fake)
    rows = httpx.post(f"{agent_server}/api/instances/logout", json={"alias": "acme"}).json()
    assert seen == [["logout", "acme", "--json"]] and rows == []
    missing = httpx.post(f"{agent_server}/api/instances/logout", json={"alias": "acme"})
    assert missing.status_code == 404


def test_every_tool_is_in_one_group():
    from ov.agent.tools import TOOL_GROUPS, TOOLS

    grouped = [name for _, _, names in TOOL_GROUPS for name in names]
    assert sorted(grouped) == sorted(t.name for t in TOOLS)
    assert len(grouped) == len(set(grouped))


def test_the_prompt_lists_tools_by_group(logged_in):
    from ov.agent.prompt import system_prompt

    text = system_prompt(False, "")
    assert "- OV CLI (signed-in OneVizion instances): ov, ov_sql, ov_export, ov_search, ov_map, ov_case" in text
    assert "Datadog (logs" not in text
    assert "- datadog: " not in text and "Workspace: none set" in text
    assert "## OV CLI" in text and "## OneVizion Basics" in text and "- ov-cli: " not in text
    assert text.index("# Skills to read") < text.index("# Core skills") < text.index("## OV CLI")


def test_skills_are_read_on_demand(logged_in):
    from ov.agent.tools import ToolError, tool_named

    skill = tool_named("skill_read")
    assert skill.handler({"name": "ov-cli"}, None).startswith("# OV CLI\n\n")
    with pytest.raises(ToolError, match="Skills: onevizion"):
        skill.handler({"name": "datadog"}, None)


def test_forgetting_an_instance_removes_its_local_data_but_keeps_runs(logged_in):
    from ov import session as session_store
    from ov.agent import datadog, graph
    from ov.agent.forget import forget, prune

    for alias in ("acme", "gone"):
        graph.graph_file(alias).write_text("{}", encoding="utf-8")
        db.create_run(f"r{alias}", "t", "m", {"prompt": "x", "instance": alias})
    db.create_run("rcase", "t", "m", {"prompt": "x", "instance": "acme.onevizion.test"})
    datadog.save_matches({"acme": "host:a", "gone": "host:b"})

    prune()
    assert not graph.graph_file("gone").exists() and graph.graph_file("acme").exists()
    assert datadog.load_state()["matches"] == {"acme": "host:a"}

    session_store.remove("acme")
    forget("acme", BASE_URL)
    assert not graph.graph_file("acme").exists()
    assert datadog.load_state()["matches"] == {}
    assert {r["id"] for r in db.list_runs()} == {"racme", "rgone", "rcase"}


def test_a_fast_model_names_the_run(logged_in, monkeypatch):
    db.save_settings({"fastModel": "fast-model"})
    seen: list[str] = []

    def fake_chat(*args, cancel, on_text):
        return StreamResult(text="Done.")

    def fake_complete(model, system, user_text):
        seen.append(model)
        return '"Tag listing question."'

    monkeypatch.setattr("ov.agent.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.copilot.complete", fake_complete)
    monkeypatch.setattr("ov.agent.copilot.supports_vision", lambda _: True)

    from ov.agent.run import runs

    run = runs.create({"prompt": "what tags are there on this instance?", "instance": "acme"}, "main-model")
    for _ in range(100):
        if run.state["summary"]["title"] == "Tag listing question":
            break
        time.sleep(0.05)

    assert run.state["summary"]["title"] == "Tag listing question"
    assert seen == ["fast-model"]


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

    monkeypatch.setattr("ov.agent.tools.run_ov", fake)
    text = tool_named("ov_export").handler({"component_type": "db_package", "ids": [12]}, FakeContext(tmp_path))

    assert "DB_PKG_NAME: PKG_BIG" in text
    assert "DB_PACKAGE_BODY: 12000 lines in db_package-12-db_package_body.txt" in text
    assert (tmp_path / "db_package-12-db_package_body.txt").read_text(encoding="utf-8") == body
    assert seen[0][2:5] == ["request", "POST", "/v3/components/exports/run"]
    with pytest.raises(ToolError, match="1 to 20"):
        tool_named("ov_export").handler({"component_type": "RULE", "ids": list(range(21))}, FakeContext(tmp_path))


def test_cut_off_tool_arguments_never_reach_copilot_again(logged_in, monkeypatch):
    cut = '{"path": "widget.html", "content": "<html><body>'
    replies = iter(
        [
            StreamResult(
                text="Writing.",
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "ov", "arguments": cut}}],
            ),
            StreamResult(text="Done in parts."),
        ]
    )
    sent: list[list[dict]] = []

    def fake_chat(model, messages, *args, cancel, on_text):
        sent.append(json.loads(json.dumps(messages)))
        reply = next(replies)
        on_text(reply.text)
        return reply

    monkeypatch.setattr("ov.agent.copilot.stream_chat", fake_chat)
    monkeypatch.setattr("ov.agent.copilot.supports_vision", lambda _: True)

    from ov.agent.run import runs

    run = runs.create({"prompt": "build it", "instance": "acme"}, "test-model")
    for _ in range(100):
        if run.state["summary"]["status"] in ("done", "error"):
            break
        time.sleep(0.05)

    assert run.state["summary"]["status"] == "done", run.state.get("error")
    second = sent[1]
    call = next(m for m in second if m.get("tool_calls"))["tool_calls"][0]
    assert call["function"]["arguments"] == "{}"
    result = next(m for m in second if m["role"] == "tool")["content"]
    assert "cut off" in result and "in parts" in result


def test_workspace_edits_are_recorded_for_the_changes_view(workspace, tmp_path):
    from ov.agent.run import _line_changes
    from ov.agent.tools import tool_named

    ctx = FakeContext(tmp_path)
    tool_named("ws_edit").handler({"path": "module/main.py", "old": "RULE_ID = 1", "new": "RULE_ID = 2\nX = 3"}, ctx)
    tool_named("ws_write").handler({"path": "module/new.py", "content": "a\nb\n"}, ctx)
    assert ctx.edits == [
        ("module/main.py", "RULE_ID = 1", "RULE_ID = 2\nX = 3", False),
        ("module/new.py", "", "a\nb\n", True),
    ]
    assert _line_changes("RULE_ID = 1", "RULE_ID = 2\nX = 3") == (2, 1)


def test_the_reducer_keeps_edits_out_of_the_thread():
    s = state.empty_state({"id": "r1", "status": "running"}, {"prompt": "hi"})
    edit = {"id": "e1", "toolId": "c1", "path": "a.py", "created": True, "added": 2, "removed": 0}
    state.reduce(s, {"seq": 1, "ts": 1, "event": {"type": "edit", "edit": edit}})
    assert s["edits"] == [edit] and s["items"] == []


def test_stopping_closes_open_questions(logged_in, monkeypatch):
    from ov.agent.run import STOPPED_ANSWER, RunError, runs

    ask = {"question": "Which instance?", "options": ["acme", "other"]}
    replies = iter(
        [
            StreamResult(
                tool_calls=[
                    {"id": "c1", "type": "function", "function": {"name": "run_ask", "arguments": json.dumps(ask)}}
                ]
            ),
            StreamResult(text="Stopped."),
        ]
    )
    monkeypatch.setattr("ov.agent.copilot.stream_chat", lambda *a, cancel, on_text: next(replies))
    monkeypatch.setattr("ov.agent.copilot.supports_vision", lambda _: True)

    run = runs.create({"prompt": "help", "instance": "acme"}, "test-model")
    for _ in range(100):
        if run.state["questions"]:
            break
        time.sleep(0.05)

    question = run.state["questions"][0]
    run.stop()
    for _ in range(100):
        if run.state["questions"][0].get("answer"):
            break
        time.sleep(0.05)

    assert run.state["questions"][0]["answer"] == STOPPED_ANSWER
    with pytest.raises(RunError, match="no longer waiting"):
        run.answer(question["id"], "acme")


def test_runs_can_be_settled_and_a_follow_up_unsettles_them(logged_in):
    db.create_run("rsettle", "t", "m", {"prompt": "x"})
    db.set_settled("rsettle", True)
    assert db.list_runs()[0]["settled"] is True
    db.set_settled("rsettle", False)
    assert "settled" not in db.list_runs()[0]
