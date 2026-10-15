from __future__ import annotations


def test_the_agent_can_give_one_call_its_own_http_timeout(logged_in, monkeypatch):
    from ov.cli.context import TIMEOUT_ENV, build_client
    from ov.core.config import Config
    from ov.onevizion.session import load

    session = load(None)
    config = Config(timeout_seconds=60)
    assert build_client(config, session)._http.timeout.read == 60
    monkeypatch.setenv(TIMEOUT_ENV, "300")
    assert build_client(config, session)._http.timeout.read == 300
