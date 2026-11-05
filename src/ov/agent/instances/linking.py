from __future__ import annotations

import re
from typing import Any

CONTEXT_CHARS = 200
MIN_NAME_CHARS = 4

_NUMBER = re.compile(r"\b\d{6,12}\b")
_QUOTED = re.compile(r"(['\"])([A-Za-z][A-Za-z0-9_$#]{2,})\1")
_OBJREF = re.compile(r"\bid\.([A-Za-z0-9_.]+)", re.IGNORECASE)
_CALL = re.compile(r"\b([A-Za-z][A-Za-z0-9_$#]*)\s*\.\s*[A-Za-z]")
OBJREF_KINDS = {"imp": "import", "rpt": "report", "wf": "workflow"}

ID_COLUMNS = (
    ("config_field_id", "field"),
    ("field_id", "field"),
    ("cf_id", "field"),
    ("xitor_type_id", "trackor_type"),
    ("trackor_type_id", "trackor_type"),
    ("parent_type_id", "trackor_type"),
    ("child_type_id", "trackor_type"),
    ("rule_id", "rule"),
    ("imp_spec_id", "import"),
    ("report_file_id", "report"),
    ("autom_id", "automation"),
    ("notif_id", "notification"),
    ("wf_template_id", "workflow"),
    ("module_id", "module"),
    ("db_package_id", "db_package"),
)
_ID_KEYWORDS = frozenset(
    {
        "and",
        "or",
        "not",
        "in",
        "is",
        "null",
        "then",
        "when",
        "where",
        "else",
        "case",
        "return",
        "values",
        "default",
        "set",
        "select",
        "from",
        "on",
        "between",
        "like",
        "constant",
        "number",
        "integer",
        "pls_integer",
        "varchar2",
        "varchar",
        "char",
        "date",
        "type",
        "rowtype",
        "if",
        "elsif",
        "loop",
    }
)
_IDENT = re.compile(r":?[A-Za-z_][A-Za-z0-9_$#]*")
_NAME_COMMENT = re.compile(r"^\s*(?:/\*\s*([^*]+?)\s*\*/|--\s*(\S+))")
_TRAILING_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_$#]*)\s*$")


def _enclosing_call(text: str) -> str | None:
    depth = 0
    for i in range(len(text) - 1, -1, -1):
        if text[i] == ")":
            depth += 1
        elif text[i] == "(":
            if depth == 0:
                call = _TRAILING_NAME.search(text[:i])
                return call.group(1) if call else None
            depth -= 1

    return None


def id_kind(before: str) -> str | None:
    text = re.split(r"[;\n]", before)[-1]
    text = re.sub(r"/\*.*?\*/", " ", re.sub(r"'[^']*'", "''", text))
    call = _enclosing_call(text)
    if call and call.lower().endswith("byid"):
        return "field"

    tokens = (token.lower() for token in reversed(_IDENT.findall(text)))
    name = next((token for token in tokens if token not in _ID_KEYWORDS), None)
    if name is None or name.startswith(":"):
        return None

    return next((kind for column, kind in ID_COLUMNS if name.endswith(column)), None)


def comment_name(after: str) -> str | None:
    match = _NAME_COMMENT.match(after)
    return (match.group(1) or match.group(2)).lower() if match else None


def as_number(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class Builder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: set[tuple[str, str, str, bool]] = set()

    def node(self, kind: str, ref: Any, name: Any, **props: Any) -> None:
        number = as_number(ref)
        if number is None:
            return

        node_id = f"{kind}:{number}"
        self.nodes[node_id] = {
            "id": node_id,
            "type": kind,
            "ref": number,
            "name": str(name or f"{kind} {number}"),
            **{k.rstrip("_"): v for k, v in props.items() if v is not None},
        }

    def edge(self, source: str, target: str, kind: str, code: bool = False) -> None:
        if source in self.nodes and target in self.nodes and source != target:
            self.edges.add((source, target, kind, code))


def objref_key(name: str) -> str:
    return name.lower().replace(" ", "_")


def objref_target(ref: str, objrefs: dict[str, str]) -> str | None:
    parts = [p for p in ref.lower().split(".") if p]
    if len(parts) >= 3 and parts[1] == "cf":
        return objrefs.get(f"id.{parts[0]}.cf.{parts[2]}")
    if len(parts) >= 2 and parts[0] in OBJREF_KINDS:
        return objrefs.get(f"id.{parts[0]}.{parts[1]}")
    return objrefs.get(f"id.{parts[0]}.tt") if parts else None


def _unique_names(nodes: dict[str, dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str | None] = {}
    for node in nodes.values():
        if node["type"] in ("field", "trackor_type", "db_package"):
            key = node["name"].upper()
            names[key] = None if key in names else node["id"]
    return {k: v for k, v in names.items() if v is not None and len(k) >= MIN_NAME_CHARS}


def _objrefs(nodes: dict[str, dict[str, Any]], edges: set[tuple[str, str, str, bool]]) -> dict[str, str]:
    owner = {s: t for s, t, k, _ in edges if k == "field_of"}
    prefixes = {kind: prefix for prefix, kind in OBJREF_KINDS.items()}
    objrefs: dict[str, str] = {}
    for node in nodes.values():
        name = objref_key(node["name"])
        if node["type"] == "trackor_type":
            objrefs[f"id.{name}.tt"] = node["id"]
        elif node["type"] == "field" and owner.get(node["id"]) in nodes:
            trackor_type = objref_key(nodes[owner[node["id"]]]["name"])
            objrefs[f"id.{trackor_type}.cf.{name}"] = node["id"]
        elif node["type"] in prefixes:
            objrefs[f"id.{prefixes[node['type']]}.{name}"] = node["id"]

    return objrefs


class Refs:
    def __init__(self, nodes: dict[str, dict[str, Any]], edges: set[tuple[str, str, str, bool]]) -> None:
        self.by_ref: dict[int, list[dict[str, Any]]] = {}
        for node in nodes.values():
            self.by_ref.setdefault(node["ref"], []).append(node)
        self.names = _unique_names(nodes)
        self.packages = {n["name"].upper(): n["id"] for n in nodes.values() if n["type"] == "db_package"}
        self.objrefs = _objrefs(nodes, edges)

    def link(self, builder: Builder, source: str, text: str) -> None:
        targets = {
            found["id"]
            for match in _NUMBER.finditer(text)
            if (
                found := self.number(
                    match.group(0),
                    text[max(0, match.start() - CONTEXT_CHARS) : match.start()],
                    text[match.end() : match.end() + CONTEXT_CHARS],
                )
            )
        }
        targets |= {self.names[q.upper()] for _, q in _QUOTED.findall(text) if q.upper() in self.names}
        targets |= {found for ref in _OBJREF.findall(text) if (found := objref_target(ref, self.objrefs))}
        targets |= {self.packages[name.upper()] for name in _CALL.findall(text) if name.upper() in self.packages}
        for target in targets:
            kind = "calls" if target.startswith("db_package:") else "uses"
            builder.edge(source, target, kind, code=True)

    def number(self, number: str, before: str, after: str) -> dict[str, Any] | None:
        candidates = self.by_ref.get(int(number), [])
        kind = id_kind(before)
        if kind:
            return next((n for n in candidates if n["type"] == kind), None)
        name = comment_name(after)
        return next((n for n in candidates if name and n["name"].lower() == name), None)
