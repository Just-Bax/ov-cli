from __future__ import annotations

import threading

import pytest
from helpers.agent import isolated_agent_db, workspace_folder

from ov.agent.api.handler import Handler
from ov.agent.api.server import AgentServer


@pytest.fixture(autouse=True)
def fresh_db(ov_home, monkeypatch):
    yield from isolated_agent_db(monkeypatch)


@pytest.fixture
def workspace(tmp_path):
    yield from workspace_folder(tmp_path)


@pytest.fixture
def agent_server(logged_in):
    httpd = AgentServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
