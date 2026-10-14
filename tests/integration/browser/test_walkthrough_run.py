from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ov.agent.storage import db
from ov.agent.walkthroughs import DRIVER_PROMPT, runner
from ov.onevizion.login import browser_is_installed
from ov.onevizion.session import Session

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(not browser_is_installed(), reason="chromium is not installed for playwright"),
]

PAGE = b"""<!doctype html><html><body>
<h1 id=title>Rules</h1>
<input aria-label="Rule name" />
<button id=save>Save rule</button>
<button onclick="t.textContent='Deleted'">Delete all rules</button>
<script>
  const t = document.getElementById('title')
  document.getElementById('save').onclick = () => { t.textContent = 'Saved ' + document.querySelector('input').value }
</script>
</body></html>"""

RUN_POLL_SECONDS = 0.1
RUN_TIMEOUT = 25


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)


@pytest.fixture
def site():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def signed_in(site, monkeypatch):
    found = {"alias": "local", "host": "127.0.0.1", "tenant": None, "url": site}
    monkeypatch.setattr("ov.agent.walkthroughs.find_instance", lambda _ref: found)
    session = Session(base_url=site, alias="local", mode="session")
    session.cookies = {"JSESSIONID": "x"}
    monkeypatch.setattr("ov.agent.walkthroughs.session_store.all_sessions", lambda: {"local": session})


def _fake_complete(actions):
    steps = iter(actions)

    def complete(model, system, user_text, max_tokens=800):
        if system == DRIVER_PROMPT:
            return json.dumps(next(steps)), None
        return json.dumps({"ok": True, "why": ""}), None

    return complete


def _wait(run_id):
    deadline = time.monotonic() + RUN_TIMEOUT
    while time.monotonic() < deadline:
        run = db.get_walk_run(run_id)
        if run["status"] not in ("pending", "running"):
            return run
        time.sleep(RUN_POLL_SECONDS)
    raise AssertionError("walkthrough run did not finish")


def test_a_walkthrough_runs_against_the_page_and_passes(signed_in, monkeypatch):
    actions = [
        {"action": "fill", "index": 0, "text": "My rule", "reason": "name it"},
        {"action": "pass", "reason": "named"},
        {"action": "click", "index": 1, "reason": "Save rule"},
        {"action": "pass", "reason": "saved"},
        {"action": "assert", "text": "Saved My rule", "reason": "it saved"},
    ]
    monkeypatch.setattr("ov.agent.walkthroughs.copilot.complete", _fake_complete(actions))
    monkeypatch.setattr("ov.agent.storage.db.get_preferences", lambda: {"fastModel": "", "defaultModel": "m"})

    plan = {"instance": "local", "title": "Save a rule", "goal": "save a rule", "steps": ["Name it", "Save", "See it"]}
    run = runner.start(plan, "m", None)
    done = _wait(run["id"])

    assert done["status"] == "passed"
    assert [s["status"] for s in done["steps"]] == ["passed", "passed", "passed"]
    assert done["steps"][0]["screenshot"] == "step-1.png"


def test_a_destructive_click_stops_the_run(signed_in, monkeypatch):
    actions = [{"action": "click", "index": 2, "reason": "clear them"}]
    monkeypatch.setattr("ov.agent.walkthroughs.copilot.complete", _fake_complete(actions))
    monkeypatch.setattr("ov.agent.storage.db.get_preferences", lambda: {"fastModel": "", "defaultModel": "m"})

    plan = {"instance": "local", "title": "Open rules", "goal": "open the rules page", "steps": ["Open rules"]}
    run = runner.start(plan, "m", None)
    done = _wait(run["id"])

    assert done["status"] == "blocked"
    assert "destructive" in done["steps"][0]["detail"]
