from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .errors import OvError
from .spec import Operation, Param, kebab, path_param_names

JSON_MEDIA = "application/json"

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
    accept: str = JSON_MEDIA

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
    slug = kebab(param.name)
    return None if slug in RESERVED_FLAGS else slug


def dest_name(param: Param) -> str:
    return "spec_" + kebab(param.name).replace("-", "_")


def build_plan(
    operation: Operation,
    values: dict[str, Any],
    *,
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

    request_headers = _pairs(headers, "-H", separator=":")
    for param in operation.header_params:
        if param.name in supplied:
            request_headers[param.name] = str(supplied[param.name])

    plan = RequestPlan(
        method=operation.method,
        path=_fill_path(operation, supplied),
        params=_query(operation, supplied, _pairs(query, "-q")),
        headers=request_headers,
        accept=accept or _accept_for(operation),
    )
    _attach_body(plan, operation, data, fields, files)
    return plan


def _query(operation: Operation, supplied: dict[str, Any], extra: dict[str, str]) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []
    for param in operation.query_params:
        if param.name in supplied:
            params.extend(_as_pairs(param.name, supplied[param.name]))
        elif param.required and param.name not in extra:
            raise OvError(
                f"Missing required query parameter '{param.name}'. Pass {param.flag} or -q {param.name}=VALUE."
            )

    for name, value in extra.items():
        params.extend(_as_pairs(name, value))
    return params


def _accept_for(operation: Operation) -> str:
    if not operation.produces or any("json" in media for media in operation.produces):
        return JSON_MEDIA
    return operation.produces[0]


def _fill_path(operation: Operation, supplied: dict[str, Any]) -> str:
    path = operation.path
    for name in path_param_names(operation.path):
        if name not in supplied:
            raise OvError(
                f"Missing path parameter '{name}' for {operation.ref}. "
                f"Pass --{name.replace('_', '-')} or -p {name}=VALUE."
            )
        path = path.replace("{" + name + "}", quote(str(supplied[name]), safe=""))
    return path


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
        _attach_multipart(plan, uploads, body, built)
        return

    if body is not None and built:
        raise OvError("--data and --field both set a body; use one of them.")
    if body is None and not built:
        if operation.body and operation.body.required:
            raise OvError(
                f"{operation.ref} requires a request body. "
                "Pass --data '{...}', --data @file.json, --data - or --field k=v."
            )
        return

    payload = built if body is None else body
    if raw_body:
        _attach_raw(plan, operation, payload)
    else:
        plan.json_body = payload


def _attach_multipart(plan: RequestPlan, uploads: dict[str, Any], body: Any, built: dict[str, Any]) -> None:
    if body is not None:
        raise OvError("--data and --file cannot be combined; put scalars in --field.")
    plan.files = uploads
    plan.files.update({name: (None, _form_value(value)) for name, value in built.items()})


def _form_value(value: Any) -> str:
    return json.dumps(value) if isinstance(value, (dict, list)) else str(value)


def _attach_raw(plan: RequestPlan, operation: Operation, payload: Any) -> None:
    if isinstance(payload, dict):
        raise OvError("This body is not JSON, so --field cannot build it; use --data.")
    plan.content = payload.encode("utf-8")
    if operation.body and not operation.body.is_json:
        plan.headers.setdefault("Content-Type", operation.body.content_type)


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
        uploads[name.strip()] = _upload(Path(raw.strip().lstrip("@")).expanduser())
    return uploads


def _upload(path: Path) -> tuple[str, bytes]:
    if not path.is_file():
        raise OvError(f"No such file: {path}")
    return path.name, path.read_bytes()


def _read_data(data: str | None, parse_json: bool) -> Any:
    if data is None:
        return None

    raw = _data_text(data).strip()
    if not raw:
        return None
    if not parse_json:
        return raw

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OvError(f"--data is not valid JSON: {exc}") from None


def _data_text(data: str) -> str:
    if data == "-":
        return sys.stdin.read()
    if not data.startswith("@"):
        return data

    path = Path(data[1:]).expanduser()
    if not path.is_file():
        raise OvError(f"No such file: {path}")
    return path.read_text(encoding="utf-8")


def _build_fields(fields: list[str] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for entry in fields or []:
        raw_key, found, raw_value = entry.partition("=")
        if not found:
            raise OvError(f"--field expects NAME=VALUE or NAME:=JSON, got {entry!r}")

        key, value = _field_value(raw_key.strip(), raw_value)
        _assign(payload, key.split("."), value)
    return payload


def _field_value(key: str, raw_value: str) -> tuple[str, Any]:
    if not key.endswith(":"):
        return key, raw_value

    key = key[:-1].strip()
    try:
        return key, json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise OvError(f"--field {key}:= is not valid JSON: {exc}") from None


def _assign(target: dict[str, Any], keys: list[str], value: Any) -> None:
    cursor = target
    for key in keys[:-1]:
        nested = cursor.get(key)
        if not isinstance(nested, dict):
            nested = {}
            cursor[key] = nested
        cursor = nested
    cursor[keys[-1]] = value
