from __future__ import annotations

import json

import pytest
from helpers.sessions import BASE_URL, seed_session

from ov.core import credentials, store
from ov.core.paths import config_file
from ov.onevizion import session as session_store
from ov.onevizion.session import Session


class FakeKeyring:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, name: str) -> str | None:
        return self.entries.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.entries[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        del self.entries[(service, name)]


@pytest.fixture
def keyring(monkeypatch):
    monkeypatch.delenv("OV_CREDENTIALS")
    fake = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: fake)
    return fake


def test_secrets_stay_out_of_config_json(logged_in):
    text = config_file().read_text(encoding="utf-8")
    assert "ACCESS:SECRET" not in text
    assert "JSESSIONID" not in text
    assert session_store.load().bearer_token == "ACCESS:SECRET"


def test_secrets_live_encrypted_in_the_vault(logged_in):
    from ov.core.credentials import key_file, vault_file

    text = vault_file().read_text(encoding="utf-8")
    assert "ACCESS:SECRET" not in text and "JSESSIONID" not in text
    assert json.loads(text)["version"] == 1
    assert key_file().exists()
    assert credentials.get(f"{BASE_URL}|")["bearer_token"] == "ACCESS:SECRET"


def test_the_keyring_holds_only_the_vault_key(ov_home, keyring):
    for n in range(5):
        session_store.save(
            Session(
                base_url=f"https://i{n}.onevizion.test",
                cookies={"c": "x" * 4000},
                bearer_token="A:B",
            )
        )
    credentials.put("agent:datadog", {"api_key": "k"})
    assert list(keyring.entries) == [("ov-cli", "vault-key")]
    assert session_store.load("i3").cookies == {"c": "x" * 4000}


def test_a_lost_key_is_an_error(ov_home, keyring):
    credentials.put("a", {"x": 1})
    keyring.entries.clear()
    with pytest.raises(credentials.CredentialsError, match="missing"):
        credentials.get("a")


def test_delete_removes_the_secret(ov_home, keyring):
    seed_session(BASE_URL)
    session_store.remove("acme")
    assert credentials.keys() == []


def test_no_keyring_is_an_error(ov_home, monkeypatch):
    from keyring.backends import fail

    monkeypatch.delenv("OV_CREDENTIALS")
    monkeypatch.setattr("keyring.get_keyring", lambda: fail.Keyring())
    with pytest.raises(credentials.CredentialsError, match="OV_CREDENTIALS=file"):
        seed_session(BASE_URL)


def test_writes_leave_no_temp_files(logged_in):
    store.update(timeout_seconds=30)
    leftovers = [p.name for p in logged_in.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
