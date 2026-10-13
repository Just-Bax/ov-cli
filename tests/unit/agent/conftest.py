from __future__ import annotations

import pytest
from helpers.agent import isolated_agent_db, workspace_folder


@pytest.fixture(autouse=True)
def fresh_db(ov_home, monkeypatch):
    yield from isolated_agent_db(monkeypatch)


@pytest.fixture
def workspace(tmp_path):
    yield from workspace_folder(tmp_path)
