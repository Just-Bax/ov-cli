from __future__ import annotations

from ov.cli.context import build_client
from ov.core import config as config_module
from ov.onevizion import session as session_store
from ov.onevizion.client import Client


def open_client(alias: str) -> Client:
    return build_client(config_module.load(), session_store.load(alias))


def web_session_alive(alias: str) -> bool:
    with open_client(alias) as client:
        return client.web_session_alive()
