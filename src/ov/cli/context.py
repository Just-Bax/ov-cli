from __future__ import annotations

import argparse
import os
from pathlib import Path

from .. import config as config_module
from ..cache import Cache
from ..client import Client
from ..config import Config
from ..service import OvService
from ..session import Session
from ..session import load as load_session

INSTANCE_ENV = "OV_INSTANCE"


def build_client(config: Config, session: Session) -> Client:
    """The one place a Client is constructed, so settings apply uniformly and
    tests have a single seam to substitute a transport."""
    return Client(
        session,
        timeout=float(config.timeout_seconds),
        verify=config.verify_tls,
    )


def instance_ref(args: argparse.Namespace | None = None) -> str | None:
    """Which instance this invocation targets, or None for the current one."""
    explicit = getattr(args, "instance", None) if args is not None else None
    return explicit or os.environ.get(INSTANCE_ENV) or None


class Context:
    """Per-invocation state: settings, output mode and lazily built API access.

    Built lazily so commands that never touch the network (config, help, the
    spec-driven help text) do not require a stored session.
    """

    def __init__(self, args: argparse.Namespace, config: Config | None = None) -> None:
        self.args = args
        self.config = config if config is not None else config_module.load()
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
        ttl = 0 if self.refresh else self.config.cache_ttl_seconds
        return Cache(ttl_seconds=ttl)

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
