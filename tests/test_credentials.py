from __future__ import annotations

import json

import pytest
from conftest import BASE_URL, Recorder, seed_session

from ov import credentials, store
from ov import session as session_store
from ov.client import Client
from ov.errors import ReadOnlyBlocked
from ov.paths import config_file, credentials_file
from ov.session import Session


class FakeKeyring:
    def __init__(self, fail: bool = False) -> None:
        self.entries: dict[tuple[str, str], str] = {}
        self.fail = fail

    def get_password(self, service: str, name: str) -> str | None:
        return self.entries.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("locked")
        self.entries[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        del self.entries[(service, name)]


@pytest.fixture
def keyring(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: fake)
    return fake


def test_secrets_stay_out_of_config_json(logged_in):
    text = config_file().read_text(encoding="utf-8")
    assert "ACCESS:SECRET" not in text
    assert "JSESSIONID" not in text
    assert session_store.load().bearer_token == "ACCESS:SECRET"


def test_file_fallback_holds_the_secrets(logged_in):
    stored = json.loads(credentials_file().read_text(encoding="utf-8"))
    assert stored[f"{BASE_URL}|"]["bearer_token"] == "ACCESS:SECRET"


def test_large_secrets_are_chunked_in_the_keyring(ov_home, keyring):
    cookies = {"JSESSIONID": "x" * 4500}
    session_store.save(Session(base_url=BASE_URL, cookies=cookies, bearer_token="A:B"))

    values = [v for (_, name), v in keyring.entries.items() if "#" in name]
    assert len(values) == 5
    assert all(len(v) <= credentials.CHUNK_CHARS for v in values)
    assert session_store.load().cookies == cookies
    assert not credentials_file().exists()


def test_a_smaller_rewrite_drops_stale_chunks(ov_home, keyring):
    session_store.save(Session(base_url=BASE_URL, cookies={"c": "x" * 3000}, bearer_token="A:B"))
    session_store.save(Session(base_url=BASE_URL, cookies={"c": "y"}, bearer_token="A:B"))

    assert len(keyring.entries) == 2
    assert session_store.load().cookies == {"c": "y"}


def test_logout_removes_keyring_entries(ov_home, keyring):
    seed_session(BASE_URL)
    session_store.remove("acme")
    assert keyring.entries == {}


def test_a_failing_keyring_falls_back_to_the_file(ov_home, monkeypatch):
    monkeypatch.setattr(credentials, "_keyring", lambda: FakeKeyring(fail=True))
    seed_session(BASE_URL)
    assert credentials_file().exists()
    assert session_store.load().bearer_token == "ACCESS:SECRET"


def test_plaintext_secrets_are_migrated_on_read(ov_home, keyring):
    store.update(
        sessions={
            "acme": {
                "base_url": BASE_URL,
                "alias": "acme",
                "cookies": {"JSESSIONID": "abc"},
                "bearer_token": "OLD:KEY",
            }
        },
        current="acme",
    )

    assert session_store.load().bearer_token == "OLD:KEY"
    assert "OLD:KEY" not in config_file().read_text(encoding="utf-8")
    assert keyring.entries


def test_writes_leave_no_temp_files(logged_in):
    store.update(timeout_seconds=30)
    leftovers = [p.name for p in logged_in.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_read_only_blocks_web_actions(logged_in, monkeypatch):
    monkeypatch.setenv("OV_READONLY", "1")
    recorder = Recorder()
    with Client(session_store.load(), transport=recorder.transport) as client:
        client.web_get("/api/docs/openapi/v3")
        with pytest.raises(ReadOnlyBlocked):
            client.web_get("/trackor/DeleteTrackor.do?id=1")
    assert len(recorder.requests) == 1


def test_read_only_web_paths_cannot_climb_out(monkeypatch):
    from ov.client import guard_web_read_only

    monkeypatch.setenv("OV_READONLY", "1")
    guard_web_read_only("/api/docs/openapi/v3")
    for path in ("/api/docs/../../DeleteTrackor.do", "/api/docs/%2e%2e/%2e%2e/x.do"):
        with pytest.raises(ReadOnlyBlocked):
            guard_web_read_only(path)
