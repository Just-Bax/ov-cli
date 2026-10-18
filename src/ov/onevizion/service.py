from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from ov.core.cache import Cache
from ov.core.errors import OvError, SpecUnavailable
from ov.onevizion import spec as spec_module
from ov.onevizion.client import Client
from ov.onevizion.invoke import RequestPlan
from ov.onevizion.spec import SPEC_PATH, SWAGGER_CONFIG_PATH, Operation, Spec

AUTHORIZE_PATH = "/authorize"


class OvService:
    def __init__(self, client: Client, *, cache: Cache, spec_group: str, spec_ttl_seconds: int) -> None:
        self.client = client
        self.cache = cache
        self.spec_group = spec_group
        self.spec_ttl_seconds = spec_ttl_seconds
        self._spec: Spec | None = None

    @property
    def base_url(self) -> str:
        return self.client.base_url

    def spec(self, refresh: bool = False) -> Spec:
        if self._spec is not None and not refresh:
            return self._spec
        cached = None if refresh else spec_module.load_cached(self.base_url, self.spec_group, self.spec_ttl_seconds)
        self._spec = cached if cached is not None else self.fetch_spec()
        return self._spec

    def fetch_spec(self) -> Spec:
        document = self._fetch_spec_document()
        spec_module.save_cached(self.base_url, self.spec_group, document)
        return spec_module.parse(document, self.spec_group)

    def _fetch_spec_document(self) -> dict[str, Any]:
        errors = []
        for path in self._spec_paths():
            try:
                document = self._get_spec(path).json()
            except OvError as exc:
                errors.append(f"{path}: {exc}")
                continue
            except ValueError:
                errors.append(f"{path}: response was not JSON")
                continue

            if isinstance(document, dict) and document.get("paths"):
                return document
            errors.append(f"{path}: no paths in the document")

        detail = "\n  ".join(errors)
        raise SpecUnavailable(
            f"Could not read the OpenAPI schema. The account needs the API Docs module at Read.\n  {detail}"
        )

    def _spec_paths(self) -> list[str]:
        group = self.spec_group.strip("/")
        paths = [f"{SPEC_PATH}/{group}"] if group else []
        paths.append(SPEC_PATH)
        return paths

    def _get_spec(self, path: str) -> httpx.Response:
        if self.client.session.is_static:
            return self.client.api("GET", path)
        return self.client.web_get(path)

    def spec_groups(self) -> list[str]:
        response = self._get_spec(SWAGGER_CONFIG_PATH)
        try:
            payload = response.json()
        except ValueError as exc:
            raise SpecUnavailable(f"{SWAGGER_CONFIG_PATH} did not return JSON") from exc

        if not isinstance(payload, dict):
            raise SpecUnavailable(f"{SWAGGER_CONFIG_PATH} did not return an object")
        return [entry["name"] for entry in payload.get("urls", [])]

    def operation(self, ref: str, refresh: bool = False) -> Operation:
        return self.spec(refresh=refresh).find(ref)

    def run(self, plan: RequestPlan) -> httpx.Response:
        key = self._cache_key(plan)
        cached = self.cache.get(key) if key else None
        if cached is not None:
            return _replay(cached)

        response = self.client.api(
            plan.method,
            plan.path,
            params=plan.params or None,
            json=plan.json_body,
            content=plan.content,
            files=plan.files or None,
            headers=plan.headers or None,
            accept=plan.accept,
        )

        if key:
            self.cache.set(key, _record(response))
        return response

    def _cache_key(self, plan: RequestPlan) -> str | None:
        if self.cache.ttl_seconds <= 0 or plan.method != "GET":
            return None
        if plan.json_body is not None or plan.content or plan.files:
            return None
        query = "&".join(f"{name}={value}" for name, value in sorted(plan.params))
        return f"{self.base_url}|GET|{plan.path}|{query}|{plan.accept}"

    def download(self, plan: RequestPlan, destination: Path) -> Path:
        response = self.run(plan)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return destination


def _record(response: httpx.Response) -> dict[str, Any]:
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "body": base64.b64encode(response.content).decode("ascii"),
    }


def _replay(record: dict[str, Any]) -> httpx.Response:
    headers = {"content-type": record["content_type"]} if record["content_type"] else {}
    return httpx.Response(record["status"], content=base64.b64decode(record["body"]), headers=headers)


def payload_of(response: httpx.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None

    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type or content_type.startswith("text/") or not content_type:
        try:
            return response.json()
        except ValueError:
            return response.text

    return {"content_type": content_type, "bytes": len(response.content)}
