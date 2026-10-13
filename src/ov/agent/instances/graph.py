from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ov.agent.engine.cancel import Cancel
from ov.agent.instances import components
from ov.agent.instances.ovproc import find_instance, host_of, run_ov
from ov.core.errors import EXIT_FORBIDDEN
from ov.core.paths import agent_dir, slugify, write_atomic

PAGE = 1000
CODE_PAGE = 200
MAX_PAGES = 60
PAGE_WORKERS = 4
QUERY_WORKERS = 6
CODE_CHUNKS = 10
CHUNK_CHARS = 1000
SQL_TIMEOUT_SECONDS = 180
ERROR_CHARS = 400
CONTEXT_CHARS = 200
MIN_NAME_CHARS = 4
FIND_LIMIT = 20
DESCRIBE_LIMIT = 60

INVALID_TYPES = {
    1: "import",
    3: "report",
    4: "rule",
    5: "field",
    17: "workflow",
    22: "notification",
    42: "module",
    27: "db_package",
    50: "automation",
}

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


class GraphError(Exception):
    pass


class NoAccess(GraphError):
    pass


def _code(column: str, start: str = "1") -> str:
    return ", ".join(
        f"dbms_lob.substr({column}, {CHUNK_CHARS}, {start} + {i * CHUNK_CHARS}) code{i}" for i in range(CODE_CHUNKS)
    )


def _code_text(row: dict[str, Any]) -> str:
    return "".join(str(row.get(f"CODE{i}") or "") for i in range(CODE_CHUNKS))


QUERIES: dict[str, str] = {
    "trackor_types": "select xitor_type_id, xitor_type from xitor_type",
    "relations": "select parent_type_id, child_type_id from relation_type",
    "fields": "select config_field_id, config_field_name, xitor_type_id, data_type, "
    "obj_xitor_type_id from config_field",
    "rules": "select r.rule_id, r.rule, r.is_enabled, r.is_async, r.filter_opt_id, "
    "r.primary_trackor_type_id, t.rule_type "
    "from rule r left join rule_type t on t.rule_type_id = r.rule_type_id where r.rule_id > 0",
    "rule_bindings": "select rule_id, id_num from rule_id_num where rule_id > 0",
    "rule_code": f"select rule_id, {_code('sql_text')} from rule where rule_id > 0",
    "automations": "select autom_id, autom_name, enabled, trackor_type_id from autom",
    "imports": "select imp_spec_id, name from imp_spec",
    "import_entities": "select imp_spec_id, xitor_type_id from imp_entity",
    "import_code": "select imp_spec_id, sql_text code0 from imp_data_map where sql_text is not null",
    "reports": "select report_file_id, report_name from report_files",
    "report_code": f"select report_file_id, {_code('sql_text')} from report_sql",
    "notifications": "select notif_id, notif_name, is_enabled, trackor_type_id from notif",
    "workflows": "select wf_template_id, template_name from wf_template where is_current_version = 1",
    "workflow_rules": "select s.wf_template_id, s.rule_id from wf_template_step s "
    "join wf_template t on t.wf_template_id = s.wf_template_id "
    "where t.is_current_version = 1 and s.rule_id is not null",
    "modules": "select module_id, module_name, is_enabled from module where nvl(is_archived, 0) = 0",
    "invalid": "select component_id, entity_id from invalid_object",
    "packages": "select db_package_id, db_package_name from db_package",
}

OPTIONAL = {
    "packages",
    "package_code",
    "rule_code",
    "import_code",
    "report_code",
    "workflows",
    "workflow_rules",
    "modules",
    "invalid",
    "automations",
}

_PLAIN_NODES = (
    ("trackor_types", "trackor_type", "XITOR_TYPE_ID", "XITOR_TYPE"),
    ("imports", "import", "IMP_SPEC_ID", "NAME"),
    ("reports", "report", "REPORT_FILE_ID", "REPORT_NAME"),
    ("workflows", "workflow", "WF_TEMPLATE_ID", "TEMPLATE_NAME"),
    ("packages", "db_package", "DB_PACKAGE_ID", "DB_PACKAGE_NAME"),
)
_SWITCHABLE_NODES = (
    ("automations", "automation", "AUTOM_ID", "AUTOM_NAME", "ENABLED"),
    ("notifications", "notification", "NOTIF_ID", "NOTIF_NAME", "IS_ENABLED"),
    ("modules", "module", "MODULE_ID", "MODULE_NAME", "IS_ENABLED"),
)
_KEY_EDGES = (
    ("relations", "trackor_type", "PARENT_TYPE_ID", "trackor_type", "CHILD_TYPE_ID", "parent_of"),
    ("fields", "field", "CONFIG_FIELD_ID", "trackor_type", "XITOR_TYPE_ID", "field_of"),
    ("fields", "field", "CONFIG_FIELD_ID", "trackor_type", "OBJ_XITOR_TYPE_ID", "points_to"),
    ("rules", "rule", "RULE_ID", "trackor_type", "PRIMARY_TRACKOR_TYPE_ID", "on"),
    ("rule_bindings", "rule", "RULE_ID", "field", "ID_NUM", "triggered_by"),
    ("automations", "automation", "AUTOM_ID", "trackor_type", "TRACKOR_TYPE_ID", "on"),
    ("import_entities", "import", "IMP_SPEC_ID", "trackor_type", "XITOR_TYPE_ID", "loads"),
    ("notifications", "notification", "NOTIF_ID", "trackor_type", "TRACKOR_TYPE_ID", "on"),
    ("workflow_rules", "workflow", "WF_TEMPLATE_ID", "rule", "RULE_ID", "runs"),
)
_CODE_SOURCES = (
    ("rule_code", "rule", "RULE_ID"),
    ("import_code", "import", "IMP_SPEC_ID"),
    ("report_code", "report", "REPORT_FILE_ID"),
)


def graph_file(alias: str) -> Path:
    return agent_dir("graphs") / f"{slugify(alias)}.json"


def load(alias: str) -> dict[str, Any] | None:
    path = graph_file(alias)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


SQL_REQUEST = ("request", "POST", "/v3/sql/test", "-H", "Content-Type: text/plain")


class SqlReader:
    def __init__(self, alias: str, cancel: Cancel) -> None:
        self.alias = alias
        self.cancel = cancel

    def page(self, sql: str, offset: int, size: int) -> list[dict[str, Any]]:
        paged = f"select * from ({sql}) offset {offset} rows fetch next {size} rows only"
        result = run_ov(
            [
                "-i",
                self.alias,
                *SQL_REQUEST,
                "-q",
                f"rows_count={size}",
                "-d",
                paged,
                "--json",
            ],
            timeout=SQL_TIMEOUT_SECONDS,
            cancel=self.cancel,
        )
        self.cancel.check()
        if result.code == EXIT_FORBIDDEN or "TEST_SQL" in result.message:
            raise NoAccess(f"Your account on {self.alias} has no Test SQL privilege, which reading it needs.")
        if result.code != 0:
            raise GraphError(result.message[:ERROR_CHARS] or f"ov exited {result.code}")

        data = json.loads(result.stdout)
        if data.get("status") != "SUCCESS":
            raise GraphError(str(data.get("error_message") or "SQL failed"))

        columns = [c.upper() for c in data["columns"]]
        return [dict(zip(columns, row["cells"], strict=False)) for row in data["rows"]]

    def count(self, sql: str) -> int:
        return int(self.page(f"select count(*) n from ({sql})", 0, 1)[0]["N"])

    def rows(self, sql: str, size: int = PAGE) -> list[dict[str, Any]]:
        first = self.page(sql, 0, size)
        if len(first) < size:
            return first

        pages = min(-(-self.count(sql) // size), MAX_PAGES * PAGE // size)
        with ThreadPoolExecutor(max_workers=PAGE_WORKERS) as pool:
            rest = pool.map(lambda i: self.page(sql, i * size, size), range(1, pages))
            return first + [row for batch in rest for row in batch]


def _num(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _flag(value: Any) -> bool:
    return str(value) not in ("0", "", "None")


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: set[tuple[str, str, str, bool]] = set()

    def node(self, kind: str, ref: Any, name: Any, **props: Any) -> None:
        number = _num(ref)
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


class _Refs:
    def __init__(self, nodes: dict[str, dict[str, Any]], edges: set[tuple[str, str, str, bool]]) -> None:
        self.by_ref: dict[int, list[dict[str, Any]]] = {}
        for node in nodes.values():
            self.by_ref.setdefault(node["ref"], []).append(node)
        self.names = _unique_names(nodes)
        self.packages = {n["name"].upper(): n["id"] for n in nodes.values() if n["type"] == "db_package"}
        self.objrefs = _objrefs(nodes, edges)

    def link(self, builder: _Builder, source: str, text: str) -> None:
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


def _page_size(name: str) -> int:
    return CODE_PAGE if name.endswith("_code") else PAGE


def _package_bodies(sql: SqlReader) -> list[dict[str, Any]]:
    exported = components.export(sql.alias, "DB_PACKAGE", None, sql.cancel)
    return [
        {"DB_PACKAGE_ID": values["DB_PACKAGE_ID"], "BODY": values["DB_PACKAGE_BODY"]}
        for values in map(components.fields, exported)
    ]


EXPORTS: dict[str, Callable[[SqlReader], list[dict[str, Any]]]] = {"package_code": _package_bodies}


def _read_all(sql: SqlReader, report: Callable[[str], None]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    results: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    lock = threading.Lock()

    def fetch(name: str) -> None:
        try:
            rows = EXPORTS[name](sql) if name in EXPORTS else sql.rows(QUERIES[name], _page_size(name))
        except (GraphError, components.ExportError) as exc:
            if name not in OPTIONAL or "Test SQL" in str(exc):
                raise
            with lock:
                warnings.append(f"{name}: {exc}")
            rows = []

        with lock:
            results[name] = rows
            report(f"Read {len(results)} of {len(QUERIES) + len(EXPORTS)} sources")

    with ThreadPoolExecutor(max_workers=QUERY_WORKERS) as pool:
        for future in [pool.submit(fetch, name) for name in [*EXPORTS, *QUERIES]]:
            future.result()
    return results, warnings


def build(instance: str, cancel: Cancel | None = None, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    found = find_instance(instance)
    if found is None:
        raise GraphError(f"Not signed in to {instance}.")

    report = progress or (lambda _: None)
    report("Reading the configuration")
    results, warnings = _read_all(SqlReader(found["alias"], cancel or Cancel()), report)

    report("Linking objects")
    graph = {
        **_assemble(results),
        "instance": found["alias"],
        "host": host_of(found["url"]),
        "builtAt": int(time.time() * 1000),
        "warnings": warnings,
    }
    write_atomic(graph_file(found["alias"]), json.dumps(graph))
    return graph


def _add_nodes(b: _Builder, r: dict[str, list[dict[str, Any]]]) -> None:
    for table, kind, id_column, name_column in _PLAIN_NODES:
        for row in r[table]:
            b.node(kind, row[id_column], row[name_column])
    for table, kind, id_column, name_column, enabled_column in _SWITCHABLE_NODES:
        for row in r[table]:
            b.node(kind, row[id_column], row[name_column], enabled=_flag(row.get(enabled_column)))
    for row in r["fields"]:
        b.node("field", row["CONFIG_FIELD_ID"], row["CONFIG_FIELD_NAME"], dataType=_num(row.get("DATA_TYPE")))
    for row in r["rules"]:
        b.node(
            "rule",
            row["RULE_ID"],
            row["RULE"],
            enabled=_flag(row.get("IS_ENABLED")),
            trigger=row.get("RULE_TYPE"),
            async_=_flag(row.get("IS_ASYNC")),
            filtered=bool(row.get("FILTER_OPT_ID")),
        )


def _add_key_edges(b: _Builder, r: dict[str, list[dict[str, Any]]]) -> None:
    for table, source_kind, source_column, target_kind, target_column, kind in _KEY_EDGES:
        for row in r[table]:
            source = f"{source_kind}:{_num(row.get(source_column))}"
            b.edge(source, f"{target_kind}:{_num(row.get(target_column))}", kind)


def _add_code_edges(b: _Builder, r: dict[str, list[dict[str, Any]]]) -> None:
    refs = _Refs(b.nodes, b.edges)
    for table, kind, column in _CODE_SOURCES:
        for row in r[table]:
            refs.link(b, f"{kind}:{_num(row[column])}", _code_text(row))
    for row in r["package_code"]:
        refs.link(b, f"db_package:{_num(row['DB_PACKAGE_ID'])}", row["BODY"])


def _flag_invalid(b: _Builder, r: dict[str, list[dict[str, Any]]]) -> None:
    for row in r["invalid"]:
        kind = INVALID_TYPES.get(_num(row["COMPONENT_ID"]))
        node = b.nodes.get(f"{kind}:{_num(row['ENTITY_ID'])}") if kind else None
        if node is not None:
            node["invalid"] = True


def _assemble(r: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    b = _Builder()
    _add_nodes(b, r)
    _add_key_edges(b, r)
    _add_code_edges(b, r)
    _flag_invalid(b, r)
    edges = [{"source": s, "target": t, "kind": k, **({"code": True} if c else {})} for s, t, k, c in sorted(b.edges)]
    return {"nodes": list(b.nodes.values()), "edges": edges}


def neighbors(graph: dict[str, Any], node_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    nodes = {n["id"]: n for n in graph["nodes"]}
    out = []
    for edge in graph["edges"]:
        if edge["source"] == node_id and edge["target"] in nodes:
            out.append(("out", edge["kind"], nodes[edge["target"]]))
        elif edge["target"] == node_id and edge["source"] in nodes:
            out.append(("in", edge["kind"], nodes[edge["source"]]))
    return out


def find(graph: dict[str, Any], query: str) -> list[dict[str, Any]]:
    text = query.strip().lower()
    number = _num(text.split(":")[-1])
    exact = [
        n for n in graph["nodes"] if n["name"].lower() == text or n["id"] == text or (number and n["ref"] == number)
    ]
    if exact:
        return exact
    return [n for n in graph["nodes"] if text in n["name"].lower()][:FIND_LIMIT]


LABELS = {
    "parent_of": ("is parent of", "is child of"),
    "field_of": ("is a field of", "has field"),
    "points_to": ("points to", "is pointed to by"),
    "on": ("acts on", "is acted on by"),
    "triggered_by": ("is triggered by", "triggers"),
    "loads": ("loads", "is loaded by"),
    "runs": ("runs", "is run by"),
    "uses": ("uses in code", "is used in code by"),
    "calls": ("calls", "is called by"),
}


def describe(graph: dict[str, Any], node: dict[str, Any], limit: int = DESCRIBE_LIMIT) -> str:
    groups: dict[str, list[str]] = {}
    for direction, kind, other in neighbors(graph, node["id"]):
        forward, backward = LABELS[kind]
        label = forward if direction == "out" else backward
        groups.setdefault(label, []).append(f"{other['type']} {other['name']} ({other['ref']})")

    lines = [f"{node['type']} {node['name']} ({node['ref']})"]
    if node.get("invalid"):
        lines.append("Flagged invalid: its SQL or code no longer compiles.")
    for label, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        shown = sorted(items)[:limit]
        more = f" ... and {len(items) - limit} more" if len(items) > limit else ""
        lines.append(f"- {label} ({len(items)}): " + "; ".join(shown) + more)
    if len(lines) == 1:
        lines.append("No links found.")
    return "\n".join(lines)


_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def status(alias: str) -> dict[str, Any]:
    with _jobs_lock:
        job = dict(_jobs.get(alias, {}))
    if job.get("state") == "building":
        return job

    graph = load(alias)
    built = {"builtAt": graph["builtAt"], "nodes": len(graph["nodes"]), "edges": len(graph["edges"])} if graph else {}
    return {"state": "ready" if graph else "none", **built, **job}


def start_build(alias: str) -> dict[str, Any]:
    with _jobs_lock:
        if _jobs.get(alias, {}).get("state") == "building":
            return dict(_jobs[alias])
        _jobs[alias] = {"state": "building", "step": "Starting"}

    def progress(step: str) -> None:
        with _jobs_lock:
            _jobs[alias] = {"state": "building", "step": step}

    def work() -> None:
        try:
            build(alias, progress=progress)
            outcome: dict[str, Any] = {"state": "ready"}
        except Exception as exc:
            outcome = {"state": "error", "error": str(exc) or type(exc).__name__}
        with _jobs_lock:
            _jobs[alias] = outcome

    threading.Thread(target=work, daemon=True, name=f"graph-{alias}").start()
    return status(alias)
