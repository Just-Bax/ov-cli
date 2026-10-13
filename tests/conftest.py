from __future__ import annotations

import os
import tempfile

import pytest

SESSION_HOME = tempfile.mkdtemp(prefix="ov-tests-")
os.environ["OV_HOME"] = SESSION_HOME
os.environ["OV_CREDENTIALS"] = "file"


@pytest.fixture(autouse=True)
def ov_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OV_HOME", str(tmp_path))
    monkeypatch.setenv("OV_CREDENTIALS", "file")
    return tmp_path


@pytest.fixture
def logged_in(ov_home):
    from helpers.sessions import BASE_URL, seed_session

    seed_session(BASE_URL)
    return ov_home


@pytest.fixture
def two_instances(ov_home):
    from helpers.sessions import BASE_URL, OTHER_URL, seed_session

    seed_session(OTHER_URL, token="OTHER:SECRET")
    seed_session(BASE_URL)
    return ov_home
