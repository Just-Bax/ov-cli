from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import OvError
from .spec import Operation, Param, path_param_names

# A spec parameter named like one of these loses its generated flag; -q/-p still reach it.
RESERVED_FLAGS = {
    "json",
    "no-color",
    "refresh",
    "help",
    "out",
    "raw",
    "table",
    "dry-run",
    "data",
    "field",
    "file",
    "header",
    "param",
    "query",
    "accept",
}


@dataclass
class RequestPlan:
    method: str
    path: str
    params: list[tuple[str, str]] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any = None
    content: bytes | None = None
    files: dict[str, Any] = field(default_factory=dict)
    accept: str = "application/json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "query": [list(pair) for pair in self.params],
            "headers": self.headers,
            "body": self.json_body,
            "files": sorted(self.files),
            "accept": self.accept,
        }


def flag_name(param: Param) -> str | None:
    from .spec import kebab

    slug = kebab(param.name)
    return None if slug in RESERVED_FLAGS else slug


def dest_name(param: Param) -> str:
    from .spec import kebab

    return "spec_" + kebab(param.name).replace("-", "_")


def build_plan(
    operation: Operation,
    values: dict[str, Any],
    query: list[str] | None = None,
    path_values: list[str] | None = None,
    headers: list[str] | None = None,
    fields: list[str] | None = None,
    data: str | None = None,
    files: list[str] | None = None,
    accept: str | None = None,
) -> RequestPlan:
    supplied = {p.name: values.get(dest_name(p)) for p in operation.params}
    supplied = {k: v for k, v in supplied.items() if v is not None}
    supplied.update(_pairs(path_values, "-p"))

    extra_query = _pairs(query, "-q")

    path = _fill_path(operation, supplied)

    params: list[tuple[str, str]] = []
    for param in operation.query_params:
        value = supplied.get(param.name)
        if value is None:
            if param.required and param.name not in extra_query:
                raise OvError(
                    f"Missing required query parameter '{param.name}'. "
                    f"Pass {param.flag} or -q {param.name}=VALUE."
                )
            continue
        params.extend(_as_pairs(param.name, value))
    for name, value in extra_query.items():
        params.extend(_as_pairs(name, value))

    request_headers = _pairs(headers, "-H", separator=":")
    for param in operation.header_params:
        value = supplied.get(param.name)
        if value is not None:
            request_headers[param.name] = str(value)

    plan = RequestPlan(
        method=operation.method,
        path=path,
        params=params,
        headers=request_headers,
        accept=accept or _accept_for(operation),
    )
    _attach_body(plan, operation, data, fields, files)
    return plan


def _accept_for(operation: Operation) -> str:
    if not operation.produces:
        return "application/json"
    if any("json" in media for media in operation.produces):
        return "application/json"
    return operation.produces[0]


def _fill_path(operation: Operation, supplied: dict[str, Any]) -> str:
    path = operation.path
    for name in path_param_names(operation.path):
        value = supplied.get(name)
        if value is None:
            raise OvError(
                f"Missing path parameter '{name}' for {operation.ref}. "
                f"Pass --{name.replace('_', '-')} or -p {name}=VALUE."
            )
        path = path.replace("{" + name + "}", _quote(str(value)))
    return path


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _as_pairs(name: str, value: Any) -> list[tuple[str, str]]:
    if isinstance(value, (list, tuple)):
        return [(name, str(item)) for item in value]
    if isinstance(value, bool):
        return [(name, "true" if value else "false")]
    return [(name, str(value))]


def _pairs(raw: list[str] | None, flag: str, separator: str = "=") -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in raw or []:
        name, found, value = entry.partition(separator)
        if not found:
            raise OvError(f"{flag} expects NAME{separator}VALUE, got {entry!r}")
        result[name.strip()] = value.strip()
    return result


def _attach_body(
    plan: RequestPlan,
    operation: Operation,
    data: str | None,
    fields: list[str] | None,
    files: list[str] | None,
) -> None:
    uploads = _uploads(files)
    raw_body = _wants_raw_body(plan, operation)
    body = _read_data(data, parse_json=not raw_body)
    built = _build_fields(fields)

    if uploads:
        plan.files = uploads
        # A multipart part named like a declared parameter is a form field, not a file.
        if built:
            plan.files.update(
                {
                    k: (None, json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                    for k, v in built.items()
                }
            )
        if body is not None:
            raise OvError("--data and --file cannot be combined; put scalars in --field.")
        return

    if body is not None and built:
        raise OvError("--data and --field both set a body; use one of them.")

    payload = body if body is not None else (built or None)
    if payload is None:
        if operation.body and operation.body.required:
            raise OvError(
                f"{operation.ref} requires a request body. "
                "Pass --data '{...}', --data @file.json, --data - or --field k=v."
            )
        return

    if raw_body:
        if isinstance(payload, dict):
            raise OvError("This body is not JSON, so --field cannot build it; use --data.")
        plan.content = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
        if operation.body and not operation.body.is_json:
            plan.headers.setdefault("Content-Type", operation.body.content_type)
        return

    plan.json_body = payload


def _wants_raw_body(plan: RequestPlan, operation: Operation) -> bool:
    if operation.body and not operation.body.is_json:
        return True
    for name, value in plan.headers.items():
        if name.lower() == "content-type":
            return "json" not in value.lower()
    return False


def _uploads(files: list[str] | None) -> dict[str, Any]:
    uploads: dict[str, Any] = {}
    for entry in files or []:
        name, found, raw = entry.partition("=")
        if not found:
            raise OvError(f"--file expects FIELD=@path, got {entry!r}")
        path = Path(raw.strip().lstrip("@")).expanduser()
        if not path.is_file():
            raise OvError(f"No such file: {path}")
        uploads[name.strip()] = (path.name, path.read_bytes())
    return uploads


def _read_data(data: str | None, parse_json: bool = True) -> Any:
    if data is None:
        return None
    if data == "-":
        raw = sys.stdin.read()
    elif data.startswith("@"):
        path = Path(data[1:]).expanduser()
        if not path.is_file():
            raise OvError(f"No such file: {path}")
        raw = path.read_text(encoding="utf-8")
    else:
        raw = data

    raw = raw.strip()
    if not raw:
        return None
    if not parse_json:
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OvError(f"--data is not valid JSON: {exc}") from None


def _build_fields(fields: list[str] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for entry in fields or []:
        raw_key, found, raw_value = entry.partition("=")
        if not found:
            raise OvError(f"--field expects NAME=VALUE or NAME:=JSON, got {entry!r}")

        key = raw_key.strip()
        if key.endswith(":"):
            key = key[:-1].strip()
            try:
                value: Any = json.loads(raw_value)
            except json.JSONDecodeError as exc:
                raise OvError(f"--field {key}:= is not valid JSON: {exc}") from None
        else:
            value = raw_value

        _assign(payload, key.split("."), value)
    return payload


def _assign(target: dict[str, Any], keys: list[str], value: Any) -> None:
    cursor = target
    for key in keys[:-1]:
        nested = cursor.get(key)
        if not isinstance(nested, dict):
            nested = {}
            cursor[key] = nested
        cursor = nested
    cursor[keys[-1]] = value
