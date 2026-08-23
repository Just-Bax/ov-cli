from __future__ import annotations

import json

import httpx
import pytest
from conftest import BASE_URL, seed_session

from ov import session as session_store
from ov.cli.main import main
from ov.client import Client
from ov.errors import Ambiguous, NotFound, OvError
from ov.session import Session, default_alias
from ov.tenants import parse_program_menu, resolve_tenant

MENU = {"100": "mTRAC", "200": "Boldyn", "300": "Lumen"}

# What Default.jsp actually renders, ps:writeJson inside a <script> block.
PAGE = (
    "<html><head><script>\n"
    '  var whatsNewUrl = "";\n'
    f"  var programMenu = {json.dumps(MENU)};\n"
    '  var loginAsUrl = "";\n'
    "</script></head><body>app</body></html>"
)

# A single-tenant account: Default.java only puts programMenu in the model when
# there is more than one, so the tag writes a bare null.
SINGLE = "<script>\n  var programMenu = null;\n</script>"


def run(capsys, *argv: str) -> tuple[int, str]:
    return main(list(argv)), capsys.readouterr().out


def payload(capsys, *argv: str):
    code, out = run(capsys, *argv)
    return code, json.loads(out)


# --- reading the tenant list off the page ---


def test_the_program_menu_is_parsed_from_the_page():
    assert parse_program_menu(PAGE) == MENU


def test_a_single_tenant_account_has_no_menu():
    assert parse_program_menu(SINGLE) == {}


def test_an_unreadable_page_yields_no_tenants():
    for page in ("", "<html>no script here</html>", "var programMenu = {broken;"):
        assert parse_program_menu(page) == {}


# --- naming a tenant ---


def test_a_tenant_resolves_by_name_id_or_prefix():
    assert resolve_tenant(MENU, "mTRAC") == ("100", "mTRAC")
    assert resolve_tenant(MENU, "mtrac") == ("100", "mTRAC")
    assert resolve_tenant(MENU, "100") == ("100", "mTRAC")
    assert resolve_tenant(MENU, "Bold") == ("200", "Boldyn")


def test_an_ambiguous_tenant_prefix_lists_them():
    menu = {"1": "Lumen Dev", "2": "Lumen Test"}
    with pytest.raises(Ambiguous, match="matches 2 tenants"):
        resolve_tenant(menu, "Lumen")


def test_an_unknown_tenant_names_the_real_ones():
    with pytest.raises(NotFound, match="Boldyn"):
        resolve_tenant(MENU, "nope")


def test_asking_for_a_tenant_on_a_single_tenant_account_explains_why_not():
    with pytest.raises(OvError, match="user with your email"):
        resolve_tenant({}, "mTRAC")


# --- aliases ---


def test_a_tenant_alias_is_host_slash_tenant():
    assert default_alias("https://sandbox-2022.onevizion.com", "mTRAC") == "sandbox-2022/mtrac"


def test_a_bare_host_alias_still_means_the_default_tenant():
    assert default_alias("https://acme.onevizion.com") == "acme"


def test_tenants_on_one_host_are_separate_sessions(ov_home):
    seed_session(BASE_URL)
    session_store.save(Session(base_url=BASE_URL, tenant="mTRAC", tenant_id="100",
                               cookies={"JSESSIONID": "a"}, bearer_token="M:K"))
    session_store.save(Session(base_url=BASE_URL, tenant="Boldyn", tenant_id="200",
                               cookies={"JSESSIONID": "b"}, bearer_token="B:K"))

    assert sorted(session_store.all_sessions()) == ["acme", "acme/boldyn", "acme/mtrac"]
    assert session_store.load("acme").tenant == ""
    assert session_store.load("acme/mtrac").bearer_token == "M:K"


def test_a_tenant_can_be_named_on_its_own(ov_home):
    seed_session(BASE_URL)
    session_store.save(Session(base_url=BASE_URL, tenant="mTRAC", tenant_id="100",
                               cookies={"JSESSIONID": "a"}, bearer_token="M:K"))

    assert session_store.load("mtrac").tenant_id == "100"
    assert session_store.load("mtra").tenant_id == "100"


def test_signing_in_again_to_a_tenant_replaces_that_tenant_only(ov_home):
    for token in ("FIRST:K", "SECOND:K"):
        session_store.save(Session(base_url=BASE_URL, tenant="mTRAC", tenant_id="100",
                                   cookies={"JSESSIONID": "a"}, bearer_token=token))

    assert list(session_store.all_sessions()) == ["acme/mtrac"]
    assert session_store.load("acme/mtrac").bearer_token == "SECOND:K"


# --- the switch itself ---


def recording_transport(calls: list[str], first_call_401: bool = False):
    state = {"api": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(f"{request.method} {path}")

        if path == "/CsrfToken.do":
            return httpx.Response(
                200,
                json={"headerName": "X-CSRF-TOKEN", "token": "csrf-1", "parameterName": "_csrf"},
                request=request,
            )
        if path == "/program/FormProg.do":
            calls[-1] += f"?pid={request.url.params.get('pid')}"
            return httpx.Response(200, text="", request=request)
        if path == "/widget/GenerateApiTokenForWebSession":
            return httpx.Response(
                200,
                json={"bearerToken": "TENANT:KEY", "expirationTime": "2100-01-01T00:00:00"},
                request=request,
            )
        if path == "/Default.do":
            return httpx.Response(200, text=PAGE, request=request)

        state["api"] += 1
        if first_call_401 and state["api"] == 1:
            return httpx.Response(401, text="expired", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    return httpx.MockTransport(handler)


def tenant_session() -> Session:
    return Session(
        base_url=BASE_URL,
        tenant="mTRAC",
        tenant_id="100",
        cookies={"JSESSIONID": "abc"},
        bearer_token="OLD:KEY",
        expires_at=4102444800.0,
    )


def test_the_tenant_switch_happens_before_the_token_is_minted(ov_home):
    """A token minted before the switch belongs to the default tenant.

    It would still authenticate, and would still return data, so getting the
    order wrong is silently wrong rather than an error.
    """
    calls: list[str] = []
    session = tenant_session()
    with Client(session, transport=recording_transport(calls)) as client:
        client.refresh_token()

    switch = calls.index("POST /program/FormProg.do?pid=100")
    mint = calls.index("POST /widget/GenerateApiTokenForWebSession")
    assert switch < mint
    assert session.bearer_token == "TENANT:KEY"


def test_a_refresh_after_a_401_re_enters_the_tenant(ov_home):
    """The dangerous case: the token expires mid-session and is silently
    replaced with one scoped to the wrong tenant."""
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


# --- through the CLI ---


@pytest.fixture
def tenant_server(monkeypatch):
    calls: list[str] = []
    transport = recording_transport(calls)

    from ov.cli import context as context_module
    from ov.client import Client as RealClient

    def build(config, session):
        return RealClient(session, timeout=float(config.timeout_seconds), transport=transport)

    monkeypatch.setattr(context_module, "build_client", build)
    monkeypatch.setattr("ov.cli.commands.auth.build_client", build)
    return calls


def test_tenants_lists_them_and_marks_the_current(capsys, ov_home, tenant_server):
    session_store.save(tenant_session())
    code, data = payload(capsys, "tenants", "--json")

    assert code == 0
    assert [r["name"] for r in data] == ["Boldyn", "Lumen", "mTRAC"]
    assert [r["current"] for r in data] == [False, False, True]


def test_tenants_is_refused_for_an_api_token(capsys, ov_home, tenant_server):
    session_store.save(Session(base_url=BASE_URL, mode="token", bearer_token="K:S"))
    code, data = payload(capsys, "tenants", "--json")

    assert code == 1
    assert "browser sign-in" in data["error"]


def test_login_with_a_tenant_is_refused_for_an_api_token(capsys, ov_home, tenant_server):
    code, data = payload(
        capsys, "login", BASE_URL, "--token", "K:S", "--tenant", "mTRAC", "--no-spec", "--json"
    )

    assert code == 1
    assert "--tenant needs a browser sign-in" in data["error"]


def test_naming_the_host_means_its_default_tenant(ov_home):
    """Before tenants, -i <host> was unambiguous; it has to stay that way."""
    seed_session(BASE_URL)
    session_store.save(Session(base_url=BASE_URL, tenant="mTRAC", tenant_id="100",
                               cookies={"JSESSIONID": "a"}, bearer_token="M:K"))
    session_store.save(Session(base_url=BASE_URL, tenant="Boldyn", tenant_id="200",
                               cookies={"JSESSIONID": "b"}, bearer_token="B:K"))

    for ref in ("acme", "acme.onevizion.test", BASE_URL, f"{BASE_URL}/"):
        assert session_store.load(ref).tenant == ""


def test_two_hosts_still_disambiguate_normally(ov_home):
    """The host-collapsing rule must not swallow a genuine ambiguity."""
    seed_session("https://acme-prod.onevizion.test")
    seed_session("https://acme-test.onevizion.test")
    with pytest.raises(Ambiguous):
        session_store.load("acme")
