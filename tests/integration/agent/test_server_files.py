from __future__ import annotations

import httpx

from ov.agent.storage.models import Provider


def test_uploads_round_trip(agent_server):
    response = httpx.post(
        f"{agent_server}/api/uploads",
        content=b"hello",
        headers={"Content-Type": "application/octet-stream", "X-File-Name": "a%20b.txt"},
    )
    saved = response.json()
    assert saved["name"] == "a b.txt"
    from ov.agent.engine.files import uploads_dir

    assert (uploads_dir() / saved["id"]).read_bytes() == b"hello"


def test_attachments_that_could_run_script_are_downloaded(agent_server, monkeypatch):
    from ov.agent.engine.files import attachments_dir
    from ov.agent.engine.run import runs

    monkeypatch.setattr("ov.agent.engine.run.Run.begin", lambda self, data: None)
    run = runs.create({"access": "read", "prompt": "x"}, Provider.COPILOT, "m")
    (attachments_dir(run.id) / "page.html").write_text("<script>1</script>")
    (attachments_dir(run.id) / "shot.png").write_bytes(b"png")

    html = httpx.get(f"{agent_server}/api/runs/{run.id}/files/page.html")
    assert html.headers["content-disposition"].startswith("attachment")
    assert html.headers["content-type"] == "application/octet-stream"

    png = httpx.get(f"{agent_server}/api/runs/{run.id}/files/shot.png")
    assert png.headers["content-disposition"].startswith("inline")
    assert png.headers["content-security-policy"] == "sandbox"
