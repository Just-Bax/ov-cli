from __future__ import annotations

import pytest


def test_an_instance_is_found_by_alias_or_host(logged_in):
    from helpers.sessions import BASE_URL

    from ov.agent.api.handler import HttpError
    from ov.agent.api.routes.instances import instance_alias
    from ov.agent.instances.ovproc import instances

    row = instances()[0]
    assert instance_alias(None, row["alias"]) == row["alias"]
    assert instance_alias(None, BASE_URL.split("//")[1]) == row["alias"]
    with pytest.raises(HttpError, match=r"Unknown instance: nowhere\.example\.com"):
        instance_alias(None, "nowhere.example.com")
