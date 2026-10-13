from __future__ import annotations

import argparse
import os
from pathlib import Path

from ov.core import config as config_module
from ov.core.cache import Cache
from ov.core.config import Config
from ov.onevizion.client import Client
from ov.onevizion.service import OvService
from ov.onevizion.session import Session
from ov.onevizion.session import load as load_session

INSTANCE_ENV = "OV_INSTANCE"


def build_client(config: Config, session: Session) -> Client:
    return Client(session, timeout=float(config.timeout_seconds), verify=config.verify_tls)


def instance_ref(args: argparse.Namespace) -> str | None:
    return getattr(args, "instance", None) or os.environ.get(INSTANCE_ENV) or None


class Context:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.config = config_module.load()
        self._session: Session | None = None
        self._client: Client | None = None
        self._service: OvService | None = None

    @property
    def as_json(self) -> bool:
        return bool(getattr(self.args, "json", False))

    @property
    def use_color(self) -> bool:
        return self.config.color and not getattr(self.args, "no_color", False)

    @property
    def refresh(self) -> bool:
        return bool(getattr(self.args, "refresh", False))

    @property
    def instance(self) -> str | None:
        return instance_ref(self.args)

    @property
    def cache(self) -> Cache:
        return Cache(ttl_seconds=0 if self.refresh else self.config.cache_ttl_seconds)

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = load_session(self.instance)
        return self._session

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = build_client(self.config, self.session)
        return self._client

    @property
    def service(self) -> OvService:
        if self._service is None:
            self._service = OvService(
                self.client,
                cache=self.cache,
                spec_group=self.config.spec_group,
                spec_ttl_seconds=0 if self.refresh else self.config.spec_ttl_seconds,
            )
        return self._service

    def out_path(self) -> Path | None:
        out = getattr(self.args, "out", None)
        return Path(out).expanduser() if out else None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
