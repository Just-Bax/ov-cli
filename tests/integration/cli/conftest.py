from __future__ import annotations

import pytest
from helpers.openapi import OPENAPI
from helpers.recorder import Recorder
from helpers.sessions import BASE_URL

from ov.cli import context as context_module
from ov.cli import dynamic
from ov.onevizion import spec as spec_module
from ov.onevizion.client import Client


@pytest.fixture(autouse=True)
def reset_dynamic_cache():
    dynamic.reset_cache()
    yield
    dynamic.reset_cache()


@pytest.fixture
def with_spec(logged_in):
    spec_module.save_cached(BASE_URL, "v3", OPENAPI)
    return logged_in


@pytest.fixture
def server(monkeypatch):
    recorder = Recorder()

    def build(config, session):
        return Client(
            session,
            timeout=float(config.timeout_seconds),
            verify=config.verify_tls,
            transport=recorder.transport,
        )

    monkeypatch.setattr(context_module, "build_client", build)
    monkeypatch.setattr("ov.cli.commands.auth.build_client", build)
    return recorder
