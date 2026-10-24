from __future__ import annotations

import copy

import httpx
import pytest
from helpers.cli import payload, run
from helpers.openapi import OPENAPI
from helpers.sessions import BASE_URL

from ov.cli import waiting
from ov.onevizion import spec as spec_module

PROCESS_ID = 7001


def _operation(tag: str, name: str, params: list[str]) -> dict:
    return {
        "tags": [tag],
        "operationId": name,
        "parameters": [{"name": p, "in": "path", "required": True, "schema": {"type": "string"}} for p in params],
        "responses": {"200": {"content": {"application/json": {"schema": {}}}}},
    }


@pytest.fixture
def run_spec(logged_in, monkeypatch):
    document = copy.deepcopy(OPENAPI)
    document["paths"].update(
        {
            "/v3/imports/{import_id}/run": {"post": _operation("imports", "runImport", ["import_id"])},
            "/v3/imports/runs/{process_id}": {"get": _operation("imports", "readImportRun", ["process_id"])},
            "/v3/components/exports/run": {"post": _operation("components", "runComponentsExport", [])},
        }
    )
    spec_module.save_cached(BASE_URL, "v3", document)
    monkeypatch.setattr(waiting, "POLL_SECONDS", 0)
    return logged_in


def _replies(server, statuses: list[str]) -> list[httpx.Request]:
    polled: list[httpx.Request] = []
    remaining = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        polled.append(request)
        status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return httpx.Response(200, json={"process_id": PROCESS_ID, "status": status})

    server.handler = handler
    return polled


def test_wait_follows_the_run_until_it_finishes(capsys, run_spec, server):
    polled = _replies(server, ["IN_QUEUE", "RUNNING", "RUNNING_IMPORTING_DATA", "EXECUTED_WITHOUT_ERRORS"])

    code, data = payload(capsys, "imports", "run-import", "12", "--wait", "--json")

    assert code == 0
    assert data == {"process_id": PROCESS_ID, "status": "EXECUTED_WITHOUT_ERRORS"}
    assert [(r.method, r.url.path) for r in polled] == [
        ("POST", "/api/v3/imports/12/run"),
        *[("GET", f"/api/v3/imports/runs/{PROCESS_ID}")] * 3,
    ]


def test_a_failed_run_exits_with_an_error(capsys, run_spec, server):
    _replies(server, ["RUNNING", "EXECUTED_WITH_ERRORS"])

    code, data = payload(capsys, "imports", "run-import", "12", "--wait", "--json")

    assert code == 1
    assert data["status"] == "EXECUTED_WITH_ERRORS"


def test_wait_refuses_a_run_without_a_status_endpoint_before_sending_it(capsys, run_spec, server):
    code, data = payload(capsys, "components", "run-components-export", "--wait", "--json")

    assert code == 1
    assert "GET /v3/components/exports/runs/{process_id}" in data["error"]
    assert server.requests == []


def test_wait_refuses_an_operation_that_starts_no_run(capsys, run_spec, server):
    code, data = payload(capsys, "users", "get-user-by-id", "5", "--wait", "--json")

    assert code == 1
    assert "starts a run" in data["error"]
    assert server.requests == []


def test_raw_requests_do_not_offer_wait(capsys, run_spec, server):
    with pytest.raises(SystemExit) as exited:
        run(capsys, "request", "POST", "/v3/imports/12/run", "--wait")

    assert exited.value.code == 2
