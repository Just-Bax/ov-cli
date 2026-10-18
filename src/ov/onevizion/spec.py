from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ov import API_PREFIX
from ov.core.errors import Ambiguous, NotFound, SpecUnavailable
from ov.core.paths import spec_file, write_atomic

SPEC_PATH = "/api/docs/openapi"
SWAGGER_CONFIG_PATH = "/api/docs/swagger-config"

METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")

DEFAULT_TAG = "default"
DEFAULT_TYPE = "string"
AMBIGUOUS_LISTED = 15
MAX_EXPAND_DEPTH = 6
MAX_REF_CHAIN = 8

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_JAVA_SIGNATURE = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
_PATH_PARAM = re.compile(r"\{([^}]+)\}")
_TAG = re.compile(r"<[^>]+>")


def plain(text: str) -> str:
    cleaned = _TAG.sub("", text.replace("<br>", " ").replace("<br/>", " "))
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(slots=True)
class Param:
    name: str
    location: str
    required: bool = False
    type: str = DEFAULT_TYPE
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
        needle = ref.strip()
        if not needle:
            raise NotFound("No operation given.")

        tiers = (
            ([o for o in self.operations if o.ref == needle], False),
            (self._by_call(needle), False),
            ([o for o in self.operations if o.name == needle], True),
            ([o for o in self.operations if needle.lower() in o.ref.lower()], True),
        )

        for matches, decisive in tiers:
            if len(matches) == 1:
                return matches[0]
            if decisive and matches:
                raise Ambiguous(_ambiguous(needle, matches))

        raise NotFound(f"No operation matches {ref!r}. Run 'ov api list' to see them.")

    def _by_call(self, needle: str) -> list[Operation]:
        method, found, path = needle.partition(" ")
        if not found:
            return []
        return [o for o in self.operations if o.method == method.upper().strip() and o.path == path.strip()]

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
    listed = "\n".join(f"  {o.ref}  {o.method} {o.path}" for o in matches[:AMBIGUOUS_LISTED])
    hidden = len(matches) - AMBIGUOUS_LISTED
    more = f"\n  ... and {hidden} more" if hidden > 0 else ""
    return f"{ref!r} matches {len(matches)} operations:\n{listed}{more}"


def kebab(value: str) -> str:
    spaced = _CAMEL_BOUNDARY.sub("-", value.replace("_", "-").replace(" ", "-"))
    return re.sub(r"-+", "-", spaced).strip("-").lower()


def operation_name(operation_id: str, method: str, path: str) -> str:
    match = _JAVA_SIGNATURE.search(operation_id)
    if match:
        return kebab(match.group(1))
    if operation_id and not re.search(r"[\s().]", operation_id):
        return kebab(operation_id)

    segments = [s for s in path.split("/") if s and not s.startswith("{")]
    return kebab("-".join([method.lower(), *segments[-2:]])) or method.lower()


def path_param_names(path: str) -> list[str]:
    return _PATH_PARAM.findall(path)


def parse(document: dict[str, Any], group: str) -> Spec:
    try:
        return _parse(document, group)
    except KeyError as exc:
        raise SpecUnavailable(f"The schema is missing the required field {exc}.") from exc


def _parse(document: dict[str, Any], group: str) -> Spec:
    info = document["info"]
    servers = document.get("servers")

    spec = Spec(
        title=info["title"],
        version=info["version"],
        group=group,
        server=servers[0]["url"] if servers else API_PREFIX,
        fetched_at=time.time(),
    )

    used: set[str] = set()
    for path, item in document["paths"].items():
        shared = _params(item.get("parameters", []), document)
        for method in METHODS:
            if method not in item:
                continue

            operation = _operation(item[method], method, path, document, shared)
            operation.name = _unique_name(operation, used)
            spec.operations.append(operation)

    spec.operations.sort(key=lambda o: (o.tag, o.name, o.method))
    return spec


def _unique_name(operation: Operation, used: set[str]) -> str:
    name = operation.name
    if f"{operation.tag}:{name}" in used:
        name = f"{name}-{operation.method.lower()}"

    suffix = 2
    while f"{operation.tag}:{name}" in used:
        name = f"{name}-{suffix}"
        suffix += 1

    used.add(f"{operation.tag}:{name}")
    return name


def _operation(
    raw: dict[str, Any],
    method: str,
    path: str,
    document: dict[str, Any],
    shared: list[Param],
) -> Operation:
    operation_id = raw.get("operationId", "")
    params = _merge(shared, _params(raw.get("parameters", []), document))
    declared = {p.name for p in params}
    params.extend(
        Param(name=name, location="path", required=True) for name in path_param_names(path) if name not in declared
    )

    return Operation(
        name=operation_name(operation_id, method, path),
        tag=kebab(str(raw.get("tags", [DEFAULT_TAG])[0])),
        method=method.upper(),
        path=path,
        summary=plain(raw.get("summary", "")),
        description=plain(raw.get("description", "")),
        operation_id=operation_id,
        deprecated=bool(raw.get("deprecated")),
        params=params,
        body=_body(raw.get("requestBody"), document),
        produces=_produces(raw),
    )


def _produces(raw: dict[str, Any]) -> list[str]:
    return sorted({media for response in raw.get("responses", {}).values() for media in response.get("content", {})})


def _merge(shared: list[Param], own: list[Param]) -> list[Param]:
    merged = {p.name: p for p in shared}
    merged.update({p.name: p for p in own})
    return list(merged.values())


def _params(raw: list[Any], document: dict[str, Any]) -> list[Param]:
    return [_param(resolve(entry, document), document) for entry in raw]


def _param(entry: dict[str, Any], document: dict[str, Any]) -> Param:
    schema = resolve(entry.get("schema", {}), document)

    return Param(
        name=str(entry["name"]),
        location=str(entry["in"]),
        required=bool(entry.get("required")),
        type=_type_of(schema),
        description=plain(entry.get("description", "")),
        enum=[str(v) for v in schema.get("enum", [])],
        default=schema.get("default"),
    )


def _body(raw: Any, document: dict[str, Any]) -> Body | None:
    if raw is None:
        return None

    raw = resolve(raw, document)
    content = raw["content"]
    if not content:
        return None

    chosen = next((c for c in content if "json" in c), next(iter(content)))
    return Body(
        content_type=chosen,
        required=bool(raw.get("required")),
        schema=expand(content[chosen].get("schema", {}), document),
    )


def expand(node: Any, document: dict[str, Any], depth: int = 0, seen: tuple[str, ...] = ()) -> Any:
    if depth > MAX_EXPAND_DEPTH or not isinstance(node, (dict, list)):
        return node

    if isinstance(node, list):
        return [expand(item, document, depth + 1, seen) for item in node]

    ref = node.get("$ref")
    if not isinstance(ref, str):
        return {key: expand(value, document, depth + 1, seen) for key, value in node.items()}

    if ref in seen:
        return {"$ref": ref, "description": "recursive, see above"}
    return expand(resolve(node, document), document, depth + 1, (*seen, ref))


def _type_of(schema: dict[str, Any]) -> str:
    kind = schema.get("type", DEFAULT_TYPE)
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), DEFAULT_TYPE)
    if kind == "array":
        return f"array[{_type_of(schema.get('items', {}))}]"
    return str(kind)


def resolve(node: Any, document: dict[str, Any]) -> Any:
    for _ in range(MAX_REF_CHAIN):
        if not isinstance(node, dict) or "$ref" not in node:
            return node
        node = _target(node["$ref"], document)
    raise SpecUnavailable(f"$ref chain longer than {MAX_REF_CHAIN} links in the schema.")


def _target(ref: str, document: dict[str, Any]) -> Any:
    if not ref.startswith("#/"):
        raise SpecUnavailable(f"External $ref {ref!r} in the schema is not supported.")

    target: Any = document
    for part in ref[2:].split("/"):
        if not isinstance(target, dict) or part not in target:
            raise SpecUnavailable(f"The schema's $ref {ref!r} points at nothing.")
        target = target[part]
    return target


def cached_path(base_url: str, group: str) -> Path:
    return spec_file(base_url, group)


def load_cached(base_url: str, group: str, ttl_seconds: int) -> Spec | None:
    path = cached_path(base_url, group)
    if not path.exists():
        return None

    record = _read_record(path)
    if ttl_seconds > 0 and time.time() - record["fetched_at"] > ttl_seconds:
        return None

    spec = parse(record["document"], group)
    spec.fetched_at = record["fetched_at"]
    return spec


def save_cached(base_url: str, group: str, document: dict[str, Any]) -> Path:
    path = cached_path(base_url, group)
    record = {
        "base_url": base_url,
        "group": group,
        "fetched_at": time.time(),
        "document": document,
    }

    write_atomic(path, json.dumps(record))
    return path


def raw_document(base_url: str, group: str) -> dict[str, Any]:
    path = cached_path(base_url, group)
    if not path.exists():
        raise SpecUnavailable("No schema cached yet. Run 'ov spec fetch'.")
    return _read_record(path)["document"]


def _read_record(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SpecUnavailable(f"Cached schema {path} is unreadable: {exc}. Run 'ov spec fetch'.") from exc

    if not isinstance(record, dict) or not isinstance(record.get("document"), dict) or "fetched_at" not in record:
        raise SpecUnavailable(f"Cached schema {path} is incomplete. Run 'ov spec fetch'.")
    return record
