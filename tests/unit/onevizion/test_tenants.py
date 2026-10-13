from __future__ import annotations

import pytest
from helpers.sessions import BASE_URL, seed_session
from helpers.tenants import MENU, PAGE, recording_transport, tenant_session

from ov.core.errors import Ambiguous, NotFound, OvError
from ov.onevizion import session as session_store
from ov.onevizion.client import Client
from ov.onevizion.session import Session, default_alias
from ov.onevizion.tenants import parse_program_menu, resolve_tenant

SINGLE = "<script>\n  var programMenu = null;\n</script>"


def test_the_program_menu_is_parsed_from_the_page():
    assert parse_program_menu(PAGE) == MENU


def test_a_single_tenant_account_has_no_menu():
    assert parse_program_menu(SINGLE) == {}


def test_an_unreadable_page_is_an_error():
    for page in ("", "<html>no script here</html>", "var programMenu = {broken;", "var programMenu = {broken};"):
        with pytest.raises(OvError):
            parse_program_menu(page)


def test_a_tenant_resolves_by_name_id_or_prefix():
    assert resolve_tenant(MENU, "North") == ("100", "North")
    assert resolve_tenant(MENU, "north") == ("100", "North")
    assert resolve_tenant(MENU, "100") == ("100", "North")
    assert resolve_tenant(MENU, "Harb") == ("200", "Harbor")


def test_an_ambiguous_tenant_prefix_lists_them():
    menu = {"1": "Metro Dev", "2": "Metro Test"}
    with pytest.raises(Ambiguous, match="matches 2 tenants"):
        resolve_tenant(menu, "Metro")


def test_an_unknown_tenant_names_the_real_ones():
    with pytest.raises(NotFound, match="Harbor"):
        resolve_tenant(MENU, "nope")


def test_asking_for_a_tenant_on_a_single_tenant_account_explains_why_not():
    with pytest.raises(OvError, match="user with your email"):
        resolve_tenant({}, "North")


def test_a_tenant_alias_is_host_slash_tenant():
    assert default_alias("https://acme.onevizion.com", "North") == "acme/north"


def test_a_bare_host_alias_still_means_the_default_tenant():
    assert default_alias("https://acme.onevizion.com") == "acme"


def test_tenants_on_one_host_are_separate_sessions(ov_home):
    seed_session(BASE_URL)
    session_store.save(
        Session(
            base_url=BASE_URL,
            tenant="North",
            tenant_id="100",
            cookies={"JSESSIONID": "a"},
            bearer_token="M:K",
        )
    )
    session_store.save(
        Session(
            base_url=BASE_URL,
            tenant="Harbor",
            tenant_id="200",
            cookies={"JSESSIONID": "b"},
            bearer_token="B:K",
        )
    )

    assert sorted(session_store.all_sessions()) == ["acme", "acme/harbor", "acme/north"]
    assert session_store.load("acme").tenant == ""
    assert session_store.load("acme/north").bearer_token == "M:K"


def test_a_tenant_can_be_named_on_its_own(ov_home):
    seed_session(BASE_URL)
    session_store.save(
        Session(
            base_url=BASE_URL,
            tenant="North",
            tenant_id="100",
            cookies={"JSESSIONID": "a"},
            bearer_token="M:K",
        )
    )

    assert session_store.load("north").tenant_id == "100"
    assert session_store.load("nor").tenant_id == "100"


def test_signing_in_again_to_a_tenant_replaces_that_tenant_only(ov_home):
    for token in ("FIRST:K", "SECOND:K"):
        session_store.save(
            Session(
                base_url=BASE_URL,
                tenant="North",
                tenant_id="100",
                cookies={"JSESSIONID": "a"},
                bearer_token=token,
            )
        )

    assert list(session_store.all_sessions()) == ["acme/north"]
    assert session_store.load("acme/north").bearer_token == "SECOND:K"


def test_the_tenant_switch_happens_before_the_token_is_minted(ov_home):
    calls: list[str] = []
    session = tenant_session()
    with Client(session, transport=recording_transport(calls)) as client:
        client.refresh_token()

    switch = calls.index("POST /program/FormProg.do?pid=100")
    mint = calls.index("POST /widget/GenerateApiTokenForWebSession")
    assert switch < mint
    assert session.bearer_token == "TENANT:KEY"


def test_a_refresh_after_a_401_re_enters_the_tenant(ov_home):
    calls: list[str] = []
    session = tenant_session()
    with Client(session, transport=recording_transport(calls, first_call_401=True)) as client:
        client.api("GET", "/v3/users")
    assert "POST /program/FormProg.do?pid=100" in calls


def test_no_switch_happens_without_a_tenant(ov_home):
    calls: list[str] = []
    session = Session(base_url=BASE_URL, cookies={"JSESSIONID": "abc"}, bearer_token="OLD:KEY")
    with Client(session, transport=recording_transport(calls)) as client:
        client.refresh_token()
    assert not any("FormProg" in c for c in calls)


def test_the_client_reads_the_tenant_list(ov_home):
    calls: list[str] = []
    with Client(tenant_session(), transport=recording_transport(calls)) as client:
        assert client.tenants() == MENU


def test_naming_the_host_means_its_default_tenant(ov_home):
    seed_session(BASE_URL)
    session_store.save(
        Session(
            base_url=BASE_URL,
            tenant="North",
            tenant_id="100",
            cookies={"JSESSIONID": "a"},
            bearer_token="M:K",
        )
    )
    session_store.save(
        Session(
            base_url=BASE_URL,
            tenant="Harbor",
            tenant_id="200",
            cookies={"JSESSIONID": "b"},
            bearer_token="B:K",
        )
    )

    for ref in ("acme", "acme.onevizion.test", BASE_URL, f"{BASE_URL}/"):
        assert session_store.load(ref).tenant == ""


def test_two_hosts_still_disambiguate_normally(ov_home):
    seed_session("https://acme-prod.onevizion.test")
    seed_session("https://acme-test.onevizion.test")
    with pytest.raises(Ambiguous):
        session_store.load("acme")
