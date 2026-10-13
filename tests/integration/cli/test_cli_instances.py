from __future__ import annotations

import json

import pytest
from helpers.cli import payload, run
from helpers.openapi import OPENAPI
from helpers.sessions import BASE_URL, OTHER_URL

from ov.onevizion import session as session_store


def test_instances_lists_both_and_marks_the_current(capsys, two_instances, server):
    code, data = payload(capsys, "instances", "--json")
    assert code == 0
    assert [row["alias"] for row in data] == ["acme", "globex"]
    assert [row["current"] for row in data] == [True, False]


def test_i_targets_another_instance(capsys, two_instances, server):
    server.route("GET", "/api/v3/server_info", 200, {"version": "1"})
    run(capsys, "-i", "globex", "request", "GET", "/v3/server_info", "--json")
    assert str(server.last.url).startswith(OTHER_URL)
    assert server.last.headers["authorization"] == "Bearer OTHER:SECRET"


def test_i_after_the_subcommand_works_too(capsys, two_instances, server):
    run(capsys, "request", "GET", "/v3/server_info", "-i", "globex", "--json")
    assert str(server.last.url).startswith(OTHER_URL)


def test_without_i_the_current_instance_is_used(capsys, two_instances, server):
    run(capsys, "request", "GET", "/v3/server_info", "--json")
    assert str(server.last.url).startswith(BASE_URL)


def test_the_instance_env_var_is_honoured(capsys, two_instances, server, monkeypatch):
    monkeypatch.setenv("OV_INSTANCE", "globex")
    run(capsys, "request", "GET", "/v3/server_info", "--json")
    assert str(server.last.url).startswith(OTHER_URL)


def test_use_changes_what_later_commands_target(capsys, two_instances, server):
    code, _ = run(capsys, "use", "globex", "--json")
    assert code == 0
    run(capsys, "request", "GET", "/v3/server_info", "--json")
    assert str(server.last.url).startswith(OTHER_URL)


def test_each_instance_generates_commands_from_its_own_schema(capsys, two_instances, server):
    from ov.onevizion import spec as spec_module

    trimmed = json.loads(json.dumps(OPENAPI))
    del trimmed["paths"]["/v3/users/{user_id}"]
    del trimmed["paths"]["/v3/users"]

    spec_module.save_cached(BASE_URL, "v3", OPENAPI)
    spec_module.save_cached(OTHER_URL, "v3", trimmed)

    code, data = payload(capsys, "api", "tags", "--json")
    assert code == 0
    assert "users" in [row["tag"] for row in data]

    code, data = payload(capsys, "-i", "globex", "api", "tags", "--json")
    assert code == 0
    assert "users" not in [row["tag"] for row in data]


def test_a_generated_group_is_built_for_the_targeted_instance(capsys, two_instances, server):
    from ov.onevizion import spec as spec_module

    spec_module.save_cached(OTHER_URL, "v3", OPENAPI)
    server.route("GET", "/api/v3/users/42", 200, {"user_name": "jsmith"})

    code, data = payload(capsys, "-i", "globex", "users", "get-user-by-id", "42", "--json")
    assert code == 0
    assert data == {"user_name": "jsmith"}
    assert str(server.last.url).startswith(OTHER_URL)


def test_a_generated_group_is_absent_for_an_instance_without_a_schema(capsys, two_instances, server):
    from ov.onevizion import spec as spec_module

    trimmed = json.loads(json.dumps(OPENAPI))
    del trimmed["paths"]["/v3/users/{user_id}"]
    del trimmed["paths"]["/v3/users"]
    spec_module.save_cached(BASE_URL, "v3", OPENAPI)
    spec_module.save_cached(OTHER_URL, "v3", trimmed)

    with pytest.raises(SystemExit) as caught:
        run(capsys, "-i", "globex", "users", "--json")

    assert caught.value.code == 2
    assert "not a group on instance 'globex'" in capsys.readouterr().err


def test_an_instance_with_no_schema_is_told_to_fetch_one(capsys, logged_in, server):
    with pytest.raises(SystemExit):
        run(capsys, "users")
    assert "ov spec fetch" in capsys.readouterr().err


def test_login_stores_a_second_instance_without_replacing_the_first(capsys, logged_in, server):
    code, data = payload(capsys, "login", OTHER_URL, "--token", "KEY:SECRET", "--no-spec", "--json")
    assert code == 0
    assert data["alias"] == "globex"
    assert sorted(session_store.all_sessions()) == ["acme", "globex"]
    assert session_store.current_alias() == "globex"


def test_login_can_name_the_instance(capsys, ov_home, server):
    code, data = payload(capsys, "login", BASE_URL, "--as", "prod", "--token", "K:S", "--no-spec", "--json")
    assert code == 0
    assert data["alias"] == "prod"
    assert sorted(session_store.all_sessions()) == ["prod"]


def test_keep_current_stores_without_switching(capsys, logged_in, server):
    code, data = payload(
        capsys,
        "login",
        OTHER_URL,
        "--token",
        "K:S",
        "--no-spec",
        "--keep-current",
        "--json",
    )

    assert code == 0
    assert data["current"] is False
    assert session_store.current_alias() == "acme"


def test_login_without_a_url_reuses_the_current_instance(capsys, logged_in, server):
    code, data = payload(capsys, "login", "--token", "NEW:KEY", "--no-spec", "--json")
    assert code == 0
    assert data["base_url"] == BASE_URL
    assert session_store.load().bearer_token == "NEW:KEY"


def test_logout_removes_only_the_named_instance(capsys, two_instances, server):
    code, data = payload(capsys, "logout", "globex", "--json")
    assert code == 0
    assert data["alias"] == "globex"
    assert sorted(session_store.all_sessions()) == ["acme"]


def test_logout_all_removes_everything(capsys, two_instances, server):
    code, data = payload(capsys, "logout", "--all", "--json")
    assert code == 0
    assert len(data["instances"]) == 2
    assert session_store.all_sessions() == {}


def test_whoami_can_be_asked_about_a_specific_instance(capsys, two_instances, server):
    code, data = payload(capsys, "whoami", "globex", "--json")
    assert code == 0
    assert data["base_url"] == OTHER_URL
    assert data["current"] is False
