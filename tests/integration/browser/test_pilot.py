from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ov.agent.tools import browser
from ov.browser.pilot import BrowserError, Pilot, Target
from ov.onevizion.login import browser_is_installed

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(not browser_is_installed(), reason="chromium is not installed for playwright"),
]

SCREEN = (800, 600)
WAIT_SECONDS = 5
LOCALHOST = "127.0.0.1"


@dataclass
class Site:
    url: str = ""
    pages: dict[str, bytes] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)
    hits: list[str] = field(default_factory=list)


class Owner:
    def changed(self, change):
        pass

    def exited(self, pilot):
        pass


def _serve(site: Site) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            site.hits.append(path)
            if path in site.redirects:
                self.send_response(302)
                self.send_header("Location", site.redirects[path])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            body = site.pages.get(path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")

    server = HTTPServer((LOCALHOST, 0), Handler)
    site.url = f"http://{LOCALHOST}:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((LOCALHOST, 0))
        return probe.getsockname()[1]


@pytest.fixture
def sites() -> Iterator[tuple[Site, Site]]:
    instance, other = Site(), Site()
    servers = [_serve(instance), _serve(other)]
    instance.pages["/"] = (
        f'<html><body><a href="{other.url}/away">Away</a>'
        '<input type="file" id="pick" multiple '
        "onchange=\"document.getElementById('got').textContent=[...this.files].map(f=>f.name).join(',')\">"
        '<span id="got"></span><button id="plain">Plain</button></body></html>'
    ).encode()
    instance.redirects["/sso"] = f"{other.url}/sso"
    other.redirects["/sso"] = f"{instance.url}/?signed=1"
    other.pages["/away"] = b"<html><body>away</body></html>"
    try:
        yield instance, other
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


@pytest.fixture
def pilot(sites) -> Iterator[Pilot]:
    instance, _ = sites
    opened = Pilot(instance.url, {}, _free_port(), SCREEN, Owner())
    try:
        yield opened
    finally:
        opened.close()


def test_a_link_to_another_site_keeps_the_page_and_is_reported(sites, pilot):
    instance, other = sites
    pilot.goto(f"{instance.url}/")
    away = Target(locator="text=Away")
    pilot.click(away, pilot.aim(away).point, "left", 1, [])

    assert pilot.where()[1] == f"{instance.url}/"
    assert "/away" not in other.hits
    assert browser.OFF_SITE.format(urls=f"{other.url}/away") in browser._result(pilot, "Clicked.")


def test_going_to_another_site_directly_is_refused(sites, pilot):
    _, other = sites
    with pytest.raises(BrowserError, match="only opens"):
        pilot.goto(f"{other.url}/away")
    assert other.hits == []


def test_a_sign_in_redirect_through_another_site_gets_back(sites, pilot):
    instance, other = sites
    pilot.goto(f"{instance.url}/sso")

    assert pilot.where()[1] == f"{instance.url}/?signed=1"
    assert other.hits == ["/sso"] and pilot.take_blocked() == []


def test_a_file_field_takes_the_uploaded_files(sites, pilot, tmp_path):
    instance, _ = sites
    files = [tmp_path / "report.txt", tmp_path / "notes.txt"]
    for path in files:
        path.write_text("x")

    pilot.goto(f"{instance.url}/")
    field_target = Target(locator="#pick")
    pilot.upload(field_target, pilot.aim(field_target).point, [str(p) for p in files])
    pilot.wait_for("report.txt,notes.txt", "", "", WAIT_SECONDS)


def test_clicking_something_that_opens_no_file_picker_is_an_error(sites, pilot, tmp_path):
    instance, _ = sites
    path = tmp_path / "report.txt"
    path.write_text("x")

    pilot.goto(f"{instance.url}/")
    plain = Target(locator="#plain")
    with pytest.raises(BrowserError, match="did not open a file picker"):
        pilot.upload(plain, pilot.aim(plain).point, [str(path)])


def test_a_widget_preview_runs_inside_the_instance_with_its_session(sites, pilot):
    instance, _ = sites
    instance.pages["/home"] = b'<html><head><meta name="_csrf" content="tok-1"></head><body>home</body></html>'
    widget = (
        "<html><body><b id='seen'></b><script>"
        "document.getElementById('seen').textContent = "
        "window.top.document.querySelector('meta[name=_csrf]').getAttribute('content') + '@' + "
        "window.top.location.origin;"
        "</script></body></html>"
    )

    pilot.goto(f"{instance.url}/home")
    url = pilot.preview("sites-board", widget)
    pilot.goto(url)
    pilot.wait_for(f"tok-1@{instance.url}", "", "", WAIT_SECONDS)

    assert url == f"{instance.url}/ov-agent-preview/sites-board"
    assert "/ov-agent-preview/sites-board" not in instance.hits


def test_a_preview_needs_an_instance_page_first(sites, pilot):
    instance, _ = sites
    pilot.goto(f"{instance.url}/")
    with pytest.raises(BrowserError, match="Open a OneVizion page"):
        pilot.preview("w", "<html></html>")
