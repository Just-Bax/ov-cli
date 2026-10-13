from __future__ import annotations

import json
from typing import Any

import httpx


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], Any] = {}
        self.default = (200, {"ok": True})

    def route(self, method: str, path: str, status: int = 200, payload: Any = None) -> None:
        self.routes[(method.upper(), path)] = (status, payload)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self.routes.get((request.method, request.url.path), self.default)
        if isinstance(payload, str):
            return httpx.Response(status, text=payload, request=request)
        return httpx.Response(
            status,
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
            request=request,
        )

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
