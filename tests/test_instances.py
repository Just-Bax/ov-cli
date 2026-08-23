from __future__ import annotations

import json

import pytest
from conftest import BASE_URL, OPENAPI, OTHER_URL, seed_session

from ov import session as session_store
from ov import store
from ov.cli.main import main
from ov.errors import Ambiguous, NotFound, NotLoggedIn
from ov.session import Session, default_alias


def run(capsys, *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def payload(capsys, *argv: str):
    code, out = run(capsys, *argv)
    return code, json.loads(out)


def test_an_alias_comes_from_the_first_hostname_label():
    assert default_alias("https://acme.onevizion.com") == "acme"
    assert default_alias("https://ov-dev.acme.co.uk:8443") == "ov-dev"


def test_two_instances_are_stored_side_by_side(two_instances):
    sessions = session_store.all_sessions()
    assert sorted(sessions) == ["acme", "globex"]
    assert sessions["acme"].base_url == BASE_URL
    assert sessions["globex"].base_url == OTHER_URL


def test_the_last_login_becomes_current(two_instances):
    assert session_store.current_alias() == "acme"
    assert session_store.load().base_url == BASE_URL


def test_an_instance_can_be_named_by_alias_host_or_url(two_instances):
    for ref in ("globex", "globex.onevizion.test", OTHER_URL, f"{OTHER_URL}/"):
        assert session_store.load(ref).base_url == OTHER_URL


def test_an_unambiguous_prefix_resolves(two_instances):
    assert session_store.load("glo").base_url == OTHER_URL


def test_an_ambiguous_prefix_lists_the_candidates(ov_home):
    seed_session("https://acme-prod.onevizion.test")
    seed_session("https://acme-test.onevizion.test")
    with pytest.raises(Ambiguous) as caught:
        session_store.load("acme")
    assert "matches 2 instances" in str(caught.value)


def test_an_unknown_instance_names_the_known_ones(two_instances):
    with pytest.raises(NotFound) as caught:
        session_store.load("nope")
    assert "acme, globex" in str(caught.value)


def test_hosts_sharing_a_first_label_get_distinct_aliases(ov_home):
    seed_session("https://acme.onevizion.test")
    seed_session("https://acme.eu.example.test")

    aliases = sorted(session_store.all_sessions())
    assert aliases == ["acme", "acme.eu.example.test"]


def test_an_explicit_alias_cannot_steal_another_instances_name(ov_home):
    seed_session(BASE_URL)
    with pytest.raises(Ambiguous, match="already points at"):
        session_store.unique_alias(OTHER_URL, "acme")


def test_logging_in_again_keeps_the_same_alias(ov_home):
    seed_session(BASE_URL, token="FIRST:KEY")
    seed_session(BASE_URL, token="SECOND:KEY")

    sessions = session_store.all_sessions()
    assert list(sessions) == ["acme"]
    assert sessions["acme"].bearer_token == "SECOND:KEY"


def test_use_switches_the_default(two_instances):
    session_store.use("globex")
    assert session_store.current_alias() == "globex"
    assert session_store.load().base_url == OTHER_URL


def test_removing_the_current_instance_falls_back_to_another(two_instances):
    session_store.remove("acme")
    assert session_store.current_alias() == "globex"


def test_removing_the_last_instance_leaves_nothing(logged_in):
    session_store.remove("acme")
    assert session_store.all_sessions() == {}
    with pytest.raises(NotLoggedIn):
        session_store.load()


def test_a_pre_multi_instance_config_is_migrated(ov_home):
    """The old file held one unnamed session plus a base_url setting."""
    store.update(
        session={
            "base_url": BASE_URL,
            "mode": "session",
            "cookies": {"JSESSIONID": "abc"},
            "bearer_token": "OLD:KEY",
        },
        base_url=BASE_URL,
        spec_group="v3",
    )

    session = session_store.load()
    assert session.alias == "acme"
    assert session.bearer_token == "OLD:KEY"
    assert "base_url" not in store.read()


# --- through the CLI ---


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
    from ov import spec as spec_module

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
    from ov import spec as spec_module

    spec_module.save_cached(OTHER_URL, "v3", OPENAPI)
    server.route("GET", "/api/v3/users/42", 200, {"user_name": "jsmith"})

    code, data = payload(capsys, "-i", "globex", "users", "get-user-by-id", "42", "--json")
    assert code == 0
    assert data == {"user_name": "jsmith"}
    assert str(server.last.url).startswith(OTHER_URL)


def test_a_generated_group_is_absent_for_an_instance_without_a_schema(
    capsys, two_instances, server
):
    """Only the targeted instance's schema is expanded, so acme's 'users' group
    must not appear when globex is the target."""
    from ov import spec as spec_module

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
    code, data = payload(
        capsys, "login", BASE_URL, "--as", "prod", "--token", "K:S", "--no-spec", "--json"
    )
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


def test_a_static_token_instance_and_a_session_instance_coexist(ov_home):
    seed_session(BASE_URL)
    session_store.save(Session(base_url=OTHER_URL, mode="token", bearer_token="K:S"))

    assert session_store.load("acme").is_static is False
    assert session_store.load("globex").is_static is True
