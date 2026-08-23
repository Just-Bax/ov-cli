from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

BASE_URL = "https://acme.onevizion.test"
OTHER_URL = "https://globex.onevizion.test"

# operationId is the Java handler signature, which is what OneVizion's springdoc
# customizer emits. The parser has to survive it.
SIGNATURE = (
    "public com.onevizion.vo.api.v3.UserJsonModel "
    "com.onevizion.web.controller.api.v3.UserJsonApiControllerV3.{method}({args})"
)


def signature(method: str, args: str = "java.lang.Long") -> str:
    return SIGNATURE.format(method=method, args=args)


OPENAPI: dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "OneVizion API", "version": "2026.1"},
    "servers": [{"url": "/api"}],
    "paths": {
        "/v3/users/{user_id}": {
            "get": {
                "tags": ["users"],
                "operationId": signature("getUserById"),
                "summary": "Read User",
                "parameters": [
                    {
                        "name": "user_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"content": {"application/json": {"schema": {}}}}},
            },
            "delete": {
                "tags": ["users"],
                "operationId": signature("deleteUser", "java.lang.Long"),
                "summary": "Delete User",
                "responses": {"204": {}},
            },
        },
        "/v3/users": {
            "get": {
                "tags": ["users"],
                "operationId": signature("getUserByUnOrEmail", "String,String"),
                "summary": "Find User by user name or email",
                "parameters": [
                    {"name": "user_name", "in": "query", "schema": {"type": "string"}},
                    {
                        "name": "email",
                        "in": "query",
                        "schema": {"type": "string"},
                        "description": "Email address",
                    },
                ],
                "responses": {"200": {"content": {"application/json": {"schema": {}}}}},
            },
            "post": {
                "tags": ["users"],
                "operationId": signature("createUser", "UserSubmitJsonModel"),
                "summary": "Create User",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/UserSubmit"}}
                    },
                },
                "responses": {"201": {"content": {"application/json": {"schema": {}}}}},
            },
        },
        "/v3/schema/trackor_types": {
            "get": {
                "tags": ["schema"],
                "operationId": signature("getTrackorTypes", ""),
                "summary": "Read Trackor Types schema",
                "responses": {"200": {"content": {"application/json": {"schema": {}}}}},
            }
        },
        "/v3/trackor_types/{trackor_type}/trackors/search": {
            "post": {
                "tags": ["trackor-types"],
                "operationId": signature("search", "String"),
                "summary": "Search Trackors",
                "parameters": [
                    {
                        "name": "trackor_type",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "fields",
                        "in": "query",
                        "schema": {"type": "array", "items": {"type": "string"}},
                    },
                    {
                        "name": "order",
                        "in": "query",
                        "schema": {"type": "string", "enum": ["asc", "desc"]},
                    },
                    {"name": "json", "in": "query", "schema": {"type": "boolean"}},
                ],
                "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {"200": {"content": {"application/json": {"schema": {}}}}},
            }
        },
    },
    "components": {
        "schemas": {
            "UserSubmit": {
                "type": "object",
                "required": ["user_name"],
                "properties": {
                    "user_name": {"type": "string"},
                    "email": {"type": "string"},
                },
            }
        }
    },
}


@pytest.fixture(autouse=True)
def ov_home(tmp_path, monkeypatch):
    """Autouse, because anything that refreshes a token persists it: a test
    without this would rewrite the developer's own ~/.ov/config.json."""
    monkeypatch.setenv("OV_HOME", str(tmp_path))
    return tmp_path


def seed_session(base_url: str, alias: str = "", token: str = "ACCESS:SECRET", **kwargs):
    from ov import session as session_store
    from ov.session import Session

    return session_store.save(
        Session(
            base_url=base_url,
            alias=alias,
            mode="session",
            cookies={"JSESSIONID": "abc"},
            bearer_token=token,
            expires_at=4102444800.0,
            expires_text="2100-01-01T00:00:00",
        ),
        **kwargs,
    )


@pytest.fixture
def logged_in(ov_home):
    seed_session(BASE_URL)
    return ov_home


@pytest.fixture
def two_instances(ov_home):
    """Two systems signed in at once, with 'acme' left as the current one."""
    seed_session(OTHER_URL, token="OTHER:SECRET")
    seed_session(BASE_URL)
    return ov_home


@pytest.fixture
def with_spec(logged_in):
    from ov import spec as spec_module

    spec_module.save_cached(BASE_URL, "v3", OPENAPI)
    return logged_in


class Recorder:
    """A stand-in server that records what the CLI sent."""

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


@pytest.fixture
def server(monkeypatch):
    recorder = Recorder()

    from ov.cli import context as context_module
    from ov.client import Client

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


@pytest.fixture(autouse=True)
def reset_dynamic_cache():
    from ov.cli import dynamic

    dynamic.reset_cache()
    yield
    dynamic.reset_cache()
