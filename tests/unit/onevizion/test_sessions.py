from __future__ import annotations

import pytest
from helpers.sessions import BASE_URL, OTHER_URL, seed_session

from ov.core.errors import Ambiguous, NotFound, NotLoggedIn
from ov.onevizion import session as session_store
from ov.onevizion.session import Session, default_alias


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


def test_a_static_token_instance_and_a_session_instance_coexist(ov_home):
    seed_session(BASE_URL)
    session_store.save(Session(base_url=OTHER_URL, mode="token", bearer_token="K:S"))
    assert session_store.load("acme").is_static is False
    assert session_store.load("globex").is_static is True
