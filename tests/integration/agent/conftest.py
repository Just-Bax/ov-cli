from __future__ import annotations

import pytest
from helpers.agent import isolated_agent_db, start_signed_in_server, workspace_folder


@pytest.fixture(autouse=True)
def fresh_db(ov_home, monkeypatch):
    yield from isolated_agent_db(monkeypatch)


@pytest.fixture
def workspace(tmp_path):
    yield from workspace_folder(tmp_path)


@pytest.fixture
def agent_server(logged_in, monkeypatch):
    httpd, url = start_signed_in_server(monkeypatch)
    yield url
    httpd.shutdown()
    httpd.server_close()
