from __future__ import annotations

import pytest
from helpers.cli import payload
from helpers.sessions import BASE_URL

from ov.cli.main import main
from ov.onevizion import session as session_store
from ov.onevizion.session import Session


@pytest.fixture
def browser_signs_in(monkeypatch):
    fresh = Session(base_url=BASE_URL, mode="session", cookies={"JSESSIONID": "new"}, bearer_token="SHORT:LIVED")
    monkeypatch.setattr("ov.cli.commands.auth._browser_login", lambda ctx, base_url: fresh)


def test_a_web_only_sign_in_keeps_the_stored_token(capsys, browser_signs_in):
    session_store.save(
        Session(base_url=BASE_URL, mode="remembered", bearer_token="KEEP:ME", expires_at=4102444800.0, cookies={})
    )

    code, data = payload(capsys, "login", BASE_URL, "--web-only", "--json")

    stored = session_store.load("acme")
    assert code == 0 and data["status"] == "web_session_renewed"
    assert stored.mode == "remembered" and stored.bearer_token == "KEEP:ME"
    assert stored.cookies == {"JSESSIONID": "new"}


def test_a_web_only_sign_in_needs_a_stored_sign_in(capsys, browser_signs_in):
    code = main(["login", BASE_URL, "--web-only"])

    assert code != 0 and "has none" in capsys.readouterr().err
    assert session_store.aliases() == []
