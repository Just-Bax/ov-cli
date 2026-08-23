from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from . import spec as spec_module
from .cache import Cache
from .client import Client
from .errors import OvError, SpecUnavailable
from .invoke import RequestPlan
from .spec import SPEC_PATH, SWAGGER_CONFIG_PATH, Operation, Spec

AUTHORIZE_PATH = "/authorize"
SERVER_INFO_PATH = "/v3/server_info"


class OvService:
    """Everything the commands are allowed to know about OneVizion: they go
    through here rather than touching httpx or the OpenAPI document."""

    def __init__(
        self,
        client: Client,
        cache: Cache | None = None,
        spec_group: str = "v3",
        spec_ttl_seconds: int = 86400,
    ) -> None:
        self.client = client
        self.cache = cache or Cache(ttl_seconds=0)
        self.spec_group = spec_group
        self.spec_ttl_seconds = spec_ttl_seconds
        self._spec: Spec | None = None

    @property
    def base_url(self) -> str:
        return self.client.base_url

    def authorize(self) -> bool:
        """GET /api/authorize is the cheapest proof that the token still works."""
        self.client.api("GET", AUTHORIZE_PATH, accept="text/plain")
        return True

    def server_info(self) -> Any:
        return payload_of(self.client.api("GET", SERVER_INFO_PATH))

    def spec(self, refresh: bool = False) -> Spec:
        if self._spec is not None and not refresh:
            return self._spec

        if not refresh:
            cached = spec_module.load_cached(self.base_url, self.spec_group, self.spec_ttl_seconds)
            if cached is not None:
                self._spec = cached
                return cached

        self._spec = self.fetch_spec()
        return self._spec

    def cached_spec(self) -> Spec | None:
        """The spec as it is on disk, however old, for building help text
        without making the parser depend on the network."""
        if self._spec is not None:
            return self._spec
        return spec_module.load_cached(self.base_url, self.spec_group, ttl_seconds=0)

    def fetch_spec(self) -> Spec:
        document = self._fetch_spec_document()
        spec_module.save_cached(self.base_url, self.spec_group, document)
        return spec_module.parse(document, self.spec_group)

    def _fetch_spec_document(self) -> dict[str, Any]:
        errors = []
        for path in self._spec_paths():
            try:
                response = self._get_spec(path)
            except OvError as exc:
                errors.append(f"{path}: {exc}")
                continue
            try:
                document = response.json()
            except ValueError:
                errors.append(f"{path}: response was not JSON")
                continue
            if isinstance(document, dict) and document.get("paths"):
                return document
            errors.append(f"{path}: no paths in the document")

        detail = "\n  ".join(errors) or "no candidate URLs"
        raise SpecUnavailable(
            "Could not read the OpenAPI schema. The account needs the API Docs module "
            f"at Read.\n  {detail}"
        )

    def _spec_paths(self) -> list[str]:
        group = self.spec_group.strip("/")
        paths = [f"{SPEC_PATH}/{group}"] if group else []
        paths.append(SPEC_PATH)
        return paths

    def _get_spec(self, path: str) -> httpx.Response:
        """The schema lives on the web UI chain, which reads cookies; an API
        token instead has to present itself as one, which that chain accepts."""
        if self.client.session.is_static:
            return self.client.api("GET", path)
        return self.client.web_get(path)

    def spec_groups(self) -> list[str]:
        try:
            response = self.client.web_get(SWAGGER_CONFIG_PATH)
            payload = response.json()
        except (OvError, ValueError):
            return [self.spec_group]

        urls = payload.get("urls") if isinstance(payload, dict) else None
        names = [u.get("name") for u in urls or [] if isinstance(u, dict) and u.get("name")]
        return names or [self.spec_group]

    def operation(self, ref: str, refresh: bool = False) -> Operation:
        return self.spec(refresh=refresh).find(ref)

    def run(self, plan: RequestPlan) -> httpx.Response:
        key = self._cache_key(plan)
        if key:
            cached = self.cache.get(key)
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
        """Only bodiless reads are cacheable, and only within one instance.

        The base URL is part of the key because the same path means different
        data on every OneVizion system signed in.
        """
        if self.cache.ttl_seconds <= 0 or plan.method != "GET":
            return None
        if plan.json_body is not None or plan.content or plan.files:
            return None
        query = "&".join(f"{name}={value}" for name, value in sorted(plan.params))
        return f"{self.base_url}|GET|{plan.path}|{query}|{plan.accept}"

    def call(self, plan: RequestPlan) -> Any:
        return payload_of(self.run(plan))

    def download(self, plan: RequestPlan, destination: Path) -> Path:
        response = self.run(plan)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return destination


def _record(response: httpx.Response) -> dict[str, Any]:
    # Bytes, not text: an export or attachment is as cacheable as a JSON list.
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "body": base64.b64encode(response.content).decode("ascii"),
    }


def _replay(record: dict[str, Any]) -> httpx.Response:
    headers = {}
    if record.get("content_type"):
        headers["content-type"] = record["content_type"]
    return httpx.Response(
        int(record.get("status") or 200),
        content=base64.b64decode(record.get("body") or ""),
        headers=headers,
    )


def payload_of(response: httpx.Response) -> Any:
    """Give back parsed JSON when the server sent JSON, and the text otherwise.

    Several endpoints answer text/plain on success, and /authorize answers with
    an empty body, so insisting on JSON here would turn working calls into
    errors.
    """
    if response.status_code == 204 or not response.content:
        return None
    content_type = (response.headers.get("content-type") or "").lower()
    if "json" in content_type:
        try:
            return response.json()
        except ValueError:
            return response.text
    if content_type.startswith("text/") or not content_type:
        text = response.text
        try:
            return response.json()
        except ValueError:
            return text
    return {"content_type": content_type, "bytes": len(response.content)}
