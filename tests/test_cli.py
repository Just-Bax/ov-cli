from __future__ import annotations

import json

import pytest
from conftest import BASE_URL

from ov.cli.main import main


def run(capsys, *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def payload(capsys, *argv: str):
    code, out = run(capsys, *argv)
    return code, json.loads(out)


def test_no_arguments_prints_help(capsys):
    code, out = run(capsys)
    assert code == 2
    assert "Command line client for the OneVizion API" in out


def test_config_needs_no_session(capsys):
    code, data = payload(capsys, "config", "show", "--json")
    assert code == 0
    assert data["instances"] == []


def test_commands_that_need_a_session_exit_3(capsys):
    code, data = payload(capsys, "whoami", "--json")
    assert code == 3
    assert "ov login" in data["error"]


def test_api_list_reads_the_cached_schema(capsys, with_spec, server):
    code, data = payload(capsys, "api", "list", "--json")
    assert code == 0
    assert {row["ref"] for row in data} >= {"users:create-user", "schema:get-trackor-types"}


def test_api_list_filters(capsys, with_spec, server):
    code, data = payload(capsys, "api", "list", "--tag", "users", "--method", "POST", "--json")
    assert [row["ref"] for row in data] == ["users:create-user"]


def test_api_show_reports_the_generated_usage(capsys, with_spec, server):
    code, data = payload(capsys, "api", "show", "users:get-user-by-id", "--json")
    assert code == 0
    assert data["usage"] == "ov users get-user-by-id"


def test_a_schema_tag_becomes_a_command_group(capsys, with_spec, server):
    code, data = payload(capsys, "users", "--json")
    assert code == 0
    assert {row["name"] for row in data} == {
        "get-user-by-id",
        "delete-user",
        "get-user-by-un-or-email",
        "create-user",
    }


def test_a_generated_command_sends_the_request(capsys, with_spec, server):
    server.route("GET", "/api/v3/users/42", 200, {"user_name": "jsmith"})
    code, data = payload(capsys, "users", "get-user-by-id", "42", "--json")

    assert code == 0
    assert data == {"user_name": "jsmith"}
    assert server.last.url.path == "/api/v3/users/42"
    assert server.last.headers["authorization"] == "Bearer ACCESS:SECRET"


def test_a_generated_flag_becomes_a_query_parameter(capsys, with_spec, server):
    run(capsys, "users", "get-user-by-un-or-email", "--user-name", "jsmith", "--json")
    assert server.last.url.params["user_name"] == "jsmith"


def test_a_generated_command_posts_a_built_body(capsys, with_spec, server):
    server.route("POST", "/api/v3/users", 201, {"user_id": 7})
    code, data = payload(capsys, "users", "create-user", "-f", "user_name=jsmith", "--json")

    assert code == 0
    assert data == {"user_id": 7}
    assert json.loads(server.last.content) == {"user_name": "jsmith"}


def test_dry_run_sends_nothing(capsys, with_spec, server):
    code, data = payload(capsys, "users", "get-user-by-id", "42", "--dry-run", "--json")
    assert code == 0
    assert data["path"] == "/v3/users/42"
    assert server.requests == []


def test_request_reaches_a_path_the_schema_does_not_describe(capsys, logged_in, server):
    server.route("GET", "/api/internal/users", 200, {"ok": 1})
    code, data = payload(capsys, "request", "GET", "/internal/users", "--json")
    assert code == 0
    assert data == {"ok": 1}


def test_out_writes_the_body_to_a_file(capsys, logged_in, server, tmp_path):
    target = tmp_path / "out.json"
    server.route("GET", "/api/v3/server_info", 200, {"version": "2026.1"})
    code, data = payload(
        capsys, "request", "GET", "/v3/server_info", "--out", str(target), "--json"
    )

    assert code == 0
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": "2026.1"}
    assert data["path"] == str(target)


def test_an_api_error_is_reported_as_json_with_its_status(capsys, logged_in, server):
    server.route("GET", "/api/v3/users", 400, "Bad request")
    code, data = payload(capsys, "request", "GET", "/v3/users", "--json")
    assert code == 5
    assert data["status"] == 400
    assert "Bad request" in data["error"]


def test_a_forbidden_call_has_its_own_exit_code(capsys, logged_in, server):
    server.route("GET", "/api/v3/users", 403, "No privilege")
    code, _ = run(capsys, "request", "GET", "/v3/users", "--json")
    assert code == 6


def test_login_with_a_token_stores_a_static_session(capsys, ov_home, server, monkeypatch):
    code, data = payload(capsys, "login", BASE_URL, "--token", "KEY:SECRET", "--no-spec", "--json")

    assert code == 0
    assert data["mode"] == "token"
    assert data["access_key"] == "KEY"

    from ov import session as session_store

    assert session_store.load().is_static


def test_login_rejects_a_malformed_token(capsys, ov_home, server):
    code, data = payload(capsys, "login", BASE_URL, "--token", "nocolon", "--json")
    assert code == 1
    assert "accessKey:secretKey" in data["error"]


@pytest.mark.parametrize("group", ["users", "schema", "trackor-types"])
def test_every_tag_expands_without_the_network(capsys, with_spec, server, group):
    code, _ = run(capsys, group, "--json")
    assert code == 0


def test_responses_are_not_cached_by_default(capsys, logged_in, server):
    for _ in range(2):
        run(capsys, "request", "GET", "/v3/server_info", "--json")
    assert len(server.requests) == 2


def test_caching_is_opt_in_and_scoped_to_one_instance(capsys, two_instances, server):
    from ov import config as config_module

    config_module.set_value(config_module.load(), "cache_ttl_seconds", "600")

    run(capsys, "request", "GET", "/v3/server_info", "--json")
    run(capsys, "request", "GET", "/v3/server_info", "--json")
    assert len(server.requests) == 1

    # The other instance serves different data behind the same path.
    run(capsys, "-i", "globex", "request", "GET", "/v3/server_info", "--json")
    assert len(server.requests) == 2


def test_refresh_bypasses_a_cached_response(capsys, logged_in, server):
    from ov import config as config_module

    config_module.set_value(config_module.load(), "cache_ttl_seconds", "600")

    run(capsys, "request", "GET", "/v3/server_info", "--json")
    run(capsys, "request", "GET", "/v3/server_info", "--refresh", "--json")
    assert len(server.requests) == 2


def test_writes_are_never_cached(capsys, logged_in, server):
    from ov import config as config_module

    config_module.set_value(config_module.load(), "cache_ttl_seconds", "600")

    for _ in range(2):
        run(capsys, "request", "POST", "/v3/users", "-d", '{"a": 1}', "--json")
    assert len(server.requests) == 2


def test_table_renders_an_empty_list_rather_than_failing(capsys, logged_in, server):
    """An empty result is a flat list; --table used to call it unrenderable."""
    server.route("GET", "/api/v3/users", 200, [])
    code, out = run(capsys, "request", "GET", "/v3/users", "--table")

    assert code == 0
    assert "no rows" in out
