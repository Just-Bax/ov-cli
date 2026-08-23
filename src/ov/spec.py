from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import Ambiguous, NotFound, SpecUnavailable
from .paths import spec_file

SPEC_PATH = "/api/docs/openapi"
SWAGGER_CONFIG_PATH = "/api/docs/swagger-config"

METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_JAVA_SIGNATURE = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
_PATH_PARAM = re.compile(r"\{([^}]+)\}")
_TAG = re.compile(r"<[^>]+>")


def plain(text: str) -> str:
    """Strip the markup OneVizion puts in its API descriptions."""
    if not text:
        return ""
    cleaned = _TAG.sub("", text.replace("<br>", " ").replace("<br/>", " "))
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(slots=True)
class Param:
    name: str
    location: str
    required: bool = False
    type: str = "string"
    description: str = ""
    enum: list[str] = field(default_factory=list)
    default: Any = None

    @property
    def flag(self) -> str:
        return f"--{kebab(self.name)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "in": self.location,
            "required": self.required,
            "type": self.type,
            "description": self.description,
            "enum": self.enum,
            "default": self.default,
        }


@dataclass(slots=True)
class Body:
    content_type: str
    required: bool = False
    schema: dict[str, Any] = field(default_factory=dict)

    @property
    def is_multipart(self) -> bool:
        return self.content_type.startswith("multipart/")

    @property
    def is_json(self) -> bool:
        return "json" in self.content_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_type": self.content_type,
            "required": self.required,
            "schema": self.schema,
        }


@dataclass(slots=True)
class Operation:
    name: str
    tag: str
    method: str
    path: str
    summary: str = ""
    description: str = ""
    operation_id: str = ""
    deprecated: bool = False
    params: list[Param] = field(default_factory=list)
    body: Body | None = None
    produces: list[str] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.tag}:{self.name}"

    @property
    def path_params(self) -> list[Param]:
        return [p for p in self.params if p.location == "path"]

    @property
    def query_params(self) -> list[Param]:
        return [p for p in self.params if p.location == "query"]

    @property
    def header_params(self) -> list[Param]:
        return [p for p in self.params if p.location == "header"]

    def to_dict(self, verbose: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ref": self.ref,
            "tag": self.tag,
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "summary": self.summary,
            "deprecated": self.deprecated,
        }
        if verbose:
            data["description"] = self.description
            data["operation_id"] = self.operation_id
            data["parameters"] = [p.to_dict() for p in self.params]
            data["body"] = self.body.to_dict() if self.body else None
            data["produces"] = self.produces
        return data


@dataclass
class Spec:
    title: str
    version: str
    group: str
    server: str
    operations: list[Operation] = field(default_factory=list)
    fetched_at: float = 0.0

    @property
    def tags(self) -> list[str]:
        return sorted({operation.tag for operation in self.operations})

    def by_tag(self, tag: str) -> list[Operation]:
        return [o for o in self.operations if o.tag == tag]

    def find(self, ref: str) -> Operation:
        """Resolve 'tag:name', a bare name, or 'METHOD /path' to one operation."""
        needle = ref.strip()
        if not needle:
            raise NotFound("No operation given.")

        exact = [o for o in self.operations if o.ref == needle]
        if len(exact) == 1:
            return exact[0]

        if " " in needle:
            method, _, path = needle.partition(" ")
            matches = [
                o
                for o in self.operations
                if o.method == method.upper().strip() and o.path == path.strip()
            ]
            if len(matches) == 1:
                return matches[0]

        by_name = [o for o in self.operations if o.name == needle]
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            raise Ambiguous(_ambiguous(needle, by_name))

        loose = [o for o in self.operations if needle.lower() in o.ref.lower()]
        if len(loose) == 1:
            return loose[0]
        if len(loose) > 1:
            raise Ambiguous(_ambiguous(needle, loose))

        raise NotFound(f"No operation matches {ref!r}. Run 'ov api list' to see them.")

    def search(self, text: str) -> list[Operation]:
        needle = text.lower()
        return [
            o
            for o in self.operations
            if needle in o.ref.lower() or needle in o.path.lower() or needle in o.summary.lower()
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "version": self.version,
            "group": self.group,
            "server": self.server,
            "fetched_at": self.fetched_at,
            "operation_count": len(self.operations),
            "tags": self.tags,
        }


def _ambiguous(ref: str, matches: list[Operation]) -> str:
    listed = "\n".join(f"  {o.ref}  {o.method} {o.path}" for o in matches[:15])
    more = "" if len(matches) <= 15 else f"\n  ... and {len(matches) - 15} more"
    return f"{ref!r} matches {len(matches)} operations:\n{listed}{more}"


def kebab(value: str) -> str:
    """user_id -> user-id, getUserById -> get-user-by-id."""
    spaced = _CAMEL_BOUNDARY.sub("-", value.replace("_", "-").replace(" ", "-"))
    return re.sub(r"-+", "-", spaced).strip("-").lower()


def operation_name(operation_id: str, method: str, path: str) -> str:
    """Derive a typeable command name.

    OneVizion sets operationId to the Java handler's full signature (see
    OwnOpenApiCustomizer.populateOperationId), so the usable part is the method
    name buried in it. Anything else falls back to the verb and path.
    """
    match = _JAVA_SIGNATURE.search(operation_id or "")
    if match:
        return kebab(match.group(1))
    if operation_id and not re.search(r"[\s().]", operation_id):
        return kebab(operation_id)

    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    return kebab("-".join([method.lower(), *segments[-2:]])) or method.lower()


def path_param_names(path: str) -> list[str]:
    return _PATH_PARAM.findall(path)


def parse(document: dict[str, Any], group: str = "") -> Spec:
    info = document.get("info") or {}
    servers = document.get("servers") or [{}]
    spec = Spec(
        title=info.get("title") or "OneVizion API",
        version=info.get("version") or "",
        group=group,
        server=(servers[0] or {}).get("url") or "/api",
        fetched_at=time.time(),
    )

    used: set[str] = set()
    for path, item in (document.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared = _params(item.get("parameters"), document)
        for method in METHODS:
            raw = item.get(method)
            if not isinstance(raw, dict):
                continue
            spec.operations.append(_operation(raw, method, path, document, shared, used))

    spec.operations.sort(key=lambda o: (o.tag, o.name, o.method))
    return spec


def _operation(
    raw: dict[str, Any],
    method: str,
    path: str,
    document: dict[str, Any],
    shared: list[Param],
    used: set[str],
) -> Operation:
    tags = raw.get("tags") or ["default"]
    tag = kebab(str(tags[0]))
    operation_id = raw.get("operationId") or ""

    name = operation_name(operation_id, method, path)
    # Two handlers in one tag can reduce to the same name: a Java overload, or a
    # fallback name built from a path that differs only in its parameters.
    if f"{tag}:{name}" in used:
        name = f"{name}-{method.lower()}"
    suffix = 2
    while f"{tag}:{name}" in used:
        name = f"{name}-{suffix}"
        suffix += 1
    used.add(f"{tag}:{name}")

    params = _merge(shared, _params(raw.get("parameters"), document))
    declared = {p.name for p in params}
    for missing in path_param_names(path):
        if missing not in declared:
            params.append(Param(name=missing, location="path", required=True))

    return Operation(
        name=name,
        tag=tag,
        method=method.upper(),
        path=path,
        summary=plain(raw.get("summary") or ""),
        description=plain(raw.get("description") or ""),
        operation_id=operation_id,
        deprecated=bool(raw.get("deprecated")),
        params=params,
        body=_body(raw.get("requestBody"), document),
        produces=sorted(
            {
                media
                for response in (raw.get("responses") or {}).values()
                if isinstance(response, dict)
                for media in (response.get("content") or {})
            }
        ),
    )


def _merge(shared: list[Param], own: list[Param]) -> list[Param]:
    merged = {p.name: p for p in shared}
    merged.update({p.name: p for p in own})
    return list(merged.values())


def _params(raw: Any, document: dict[str, Any]) -> list[Param]:
    if not isinstance(raw, list):
        return []
    params = []
    for entry in raw:
        entry = resolve(entry, document)
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        schema = resolve(entry.get("schema") or {}, document)
        if not isinstance(schema, dict):
            schema = {}
        params.append(
            Param(
                name=str(entry["name"]),
                location=str(entry.get("in") or "query"),
                required=bool(entry.get("required")),
                type=_type_of(schema),
                description=plain(entry.get("description") or ""),
                enum=[str(v) for v in (schema.get("enum") or [])],
                default=schema.get("default"),
            )
        )
    return params


def _body(raw: Any, document: dict[str, Any]) -> Body | None:
    raw = resolve(raw, document)
    if not isinstance(raw, dict):
        return None
    content = raw.get("content") or {}
    if not content:
        return None

    # Prefer JSON when a handler accepts several encodings, since that is the
    # one a --data payload can satisfy.
    chosen = next((c for c in content if "json" in c), next(iter(content)))
    media = content.get(chosen) or {}
    schema = expand(media.get("schema") or {}, document)
    return Body(
        content_type=chosen,
        required=bool(raw.get("required")),
        schema=schema if isinstance(schema, dict) else {},
    )


def expand(node: Any, document: dict[str, Any], depth: int = 0, seen: tuple = ()) -> Any:
    """Resolve every $ref inside a schema, not just the one at its root.

    A body of {"fields": {"$ref": ...}} tells the caller nothing about what to
    send. Recursive models are cut off where they repeat.
    """
    if depth > 6 or not isinstance(node, (dict, list)):
        return node
    if isinstance(node, list):
        return [expand(item, document, depth + 1, seen) for item in node]

    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return {"$ref": ref, "description": "recursive, see above"}
        return expand(resolve(node, document), document, depth + 1, seen + (ref,))

    return {key: expand(value, document, depth + 1, seen) for key, value in node.items()}


def _type_of(schema: dict[str, Any]) -> str:
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    if kind == "array":
        items = schema.get("items") or {}
        return f"array[{_type_of(items) if isinstance(items, dict) else 'string'}]"
    return str(kind or "string")


def resolve(node: Any, document: dict[str, Any], depth: int = 0) -> Any:
    """Follow $ref far enough to describe a schema, without unrolling recursive
    models forever."""
    if depth > 8 or not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return node

    target: Any = document
    for part in ref[2:].split("/"):
        if not isinstance(target, dict) or part not in target:
            return node
        target = target[part]
    return resolve(target, document, depth + 1)


def cached_path(base_url: str, group: str) -> Path:
    return spec_file(base_url, group)


def load_cached(base_url: str, group: str, ttl_seconds: int) -> Spec | None:
    path = cached_path(base_url, group)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    fetched_at = float(record.get("fetched_at") or 0)
    if ttl_seconds > 0 and time.time() - fetched_at > ttl_seconds:
        return None

    document = record.get("document")
    if not isinstance(document, dict):
        return None

    spec = parse(document, group)
    spec.fetched_at = fetched_at
    return spec


def save_cached(base_url: str, group: str, document: dict[str, Any]) -> Path:
    path = cached_path(base_url, group)
    record = {
        "base_url": base_url,
        "group": group,
        "fetched_at": time.time(),
        "document": document,
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def raw_document(base_url: str, group: str) -> dict[str, Any]:
    path = cached_path(base_url, group)
    if not path.exists():
        raise SpecUnavailable("No schema cached yet. Run 'ov spec fetch'.")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SpecUnavailable(f"Cached schema is unreadable: {exc}") from exc
    document = record.get("document")
    if not isinstance(document, dict):
        raise SpecUnavailable("Cached schema is missing its document.")
    return document
