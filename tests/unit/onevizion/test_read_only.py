from __future__ import annotations

import pytest
from helpers.recorder import Recorder

from ov.core.errors import ReadOnlyBlocked
from ov.onevizion import session as session_store
from ov.onevizion.client import Client


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("GET", "/v3/trackors/1", True),
        ("POST", "/v3/trackor_types/Cases/trackors/search", True),
        ("POST", "/api/v3/sql/test", True),
        ("POST", "/v3/components/exports/run", True),
        ("PUT", "/v3/trackors/1", False),
        ("POST", "/v3/trackor_types/Cases/trackors", False),
        ("DELETE", "/v3/trackor_types/Cases/trackors", False),
        ("POST", "/v3/components/imports/run", False),
    ],
)
def test_read_only_guard(monkeypatch, method, path, allowed):
    from ov.onevizion.client import guard_read_only

    monkeypatch.setenv("OV_READONLY", "1")
    if allowed:
        guard_read_only(method, path)
    else:
        with pytest.raises(ReadOnlyBlocked):
            guard_read_only(method, path)


def test_read_only_guard_is_off_by_default(monkeypatch):
    from ov.onevizion.client import guard_read_only

    monkeypatch.delenv("OV_READONLY", raising=False)
    guard_read_only("DELETE", "/v3/trackors/1")


def test_read_only_blocks_web_actions(logged_in, monkeypatch):
    monkeypatch.setenv("OV_READONLY", "1")
    recorder = Recorder()
    with Client(session_store.load(), transport=recorder.transport) as client:
        client.web_get("/api/docs/openapi/v3")
        with pytest.raises(ReadOnlyBlocked):
            client.web_get("/trackor/DeleteTrackor.do?id=1")
    assert len(recorder.requests) == 1


def test_read_only_web_paths_cannot_climb_out(monkeypatch):
    from ov.onevizion.client import guard_web_read_only

    monkeypatch.setenv("OV_READONLY", "1")
    guard_web_read_only("/api/docs/openapi/v3")
    for path in ("/api/docs/../../DeleteTrackor.do", "/api/docs/%2e%2e/%2e%2e/x.do"):
        with pytest.raises(ReadOnlyBlocked):
            guard_web_read_only(path)


def test_component_import_dry_runs_pass_read_only(monkeypatch):
    from ov.onevizion.client import guard_read_only

    monkeypatch.setenv("OV_READONLY", "1")
    guard_read_only("POST", "/v3/components/imports/run", [("is_dry_run", "true")])
    guard_read_only("POST", "/v3/components/imports/run?is_dry_run=true")
    with pytest.raises(ReadOnlyBlocked):
        guard_read_only("POST", "/v3/components/imports/run", [("is_dry_run", "false")])
    with pytest.raises(ReadOnlyBlocked):
        guard_read_only("POST", "/v3/components/imports/run", [("is_dry_run", "false"), ("is_dry_run", "true")])


@pytest.mark.parametrize("path", ["/../admin/x/Delete.do?id=1", "/v3/%2e%2e/%2E%2E/admin/x.do", "v3/../../x"])
def test_api_paths_cannot_climb_out_of_the_api(path):
    from ov.core.errors import OvError
    from ov.onevizion.client import api_path

    with pytest.raises(OvError, match="step out"):
        api_path(path)
