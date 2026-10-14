from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from playwright.sync_api import sync_playwright

from ov.browser.engine import BrowserError, Session, chromium
from ov.onevizion.login import browser_is_installed

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(not browser_is_installed(), reason="chromium is not installed for playwright"),
]

PAGE = b"""<!doctype html><html><body>
<h1 id=title>Trackor 42</h1>
<input aria-label="Name" />
<select aria-label="Status"><option>Open</option><option>Closed</option></select>
<button id=save>Save</button>
<button onclick="t.textContent='Deleted'">Delete trackor</button>
<script>
  const t = document.getElementById('title')
  document.getElementById('save').onclick = () => { t.textContent = 'Saved ' + document.querySelector('input').value }
</script>
</body></html>"""


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
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


@pytest.fixture
def session(site):
    with sync_playwright() as p:
        browser = chromium(p, headless=True, debug_port=None)
        s = Session(browser, site, {"JSESSIONID": "x"}, 1024, 768)
        s.goto(site)
        yield s
        s.close()
        browser.close()


def test_the_engine_reads_clicks_and_types_like_a_user(session, tmp_path):
    names = [e.name for e in session.snapshot()]
    assert names == ["Name", "Status", "Save", "Delete trackor"]

    name_field = next(e for e in session.snapshot() if e.name == "Name")
    session.fill(name_field, "Widgets")
    save = next(e for e in session.snapshot() if e.name == "Save")
    session.click(save)
    session.wait_for_text("Saved Widgets")
    assert "Saved Widgets" in session.text()

    shot = tmp_path / "step.png"
    session.screenshot(shot)
    assert shot.stat().st_size > 0


def test_a_stale_element_raises_a_clear_error(session):
    ref = session.snapshot()[0]
    ref.index = 99
    with pytest.raises(BrowserError, match="no longer on the page"):
        session.click(ref)
