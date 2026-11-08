from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ov.agent.engine.cancel import Cancel
from ov.agent.instances import access, components, graph_export
from ov.agent.instances.linking import Builder, Refs, as_number
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
FIND_LIMIT = 20
DESCRIBE_LIMIT = 60
RECHECK_SECONDS = 300
SOURCE_SQL = "sql"
SOURCE_EXPORT = "export"
NO_SOURCE = (
    "Your account on {instance} has neither the Test SQL nor the component export privilege, and the map needs "
    "one of them. Ask an administrator for Test SQL or Components Export/Import (BPL_EXP_IMP) read access."
)

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
    "workflows": "select wf_template_id, template_name from wf_template t where {current}",
    "workflow_rules": "select s.wf_template_id, s.rule_id from wf_template_step s "
    "join wf_template t on t.wf_template_id = s.wf_template_id "
    "where {current} and s.rule_id is not null",
    "modules": "select module_id, module_name, is_enabled from module where nvl(is_archived, 0) = 0",
    "invalid": "select component_id, entity_id from invalid_object",
    "packages": "select db_package_id, db_package_name from db_package",
}

VERSIONED_WORKFLOWS_SQL = (
    "select count(*) n from all_tab_columns where table_name = 'WF_TEMPLATE' and column_name = 'IS_CURRENT_VERSION'"
)
CURRENT_VERSION = "t.is_current_version = 1"
EVERY_VERSION = "1 = 1"
WORKFLOW_QUERIES = ("workflows", "workflow_rules")

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

CHANGE_SOURCES: dict[int, tuple[str, tuple[str, ...]]] = {
    1: ("imports", ("imports", "import_entities", "import_code")),
    3: ("reports", ("reports", "report_code")),
    4: ("rules", ("rules", "rule_bindings", "rule_code")),
    5: ("fields", ("fields",)),
    11: ("trackor types", ("trackor_types",)),
    12: ("relations", ("relations",)),
    17: ("workflows", ("workflows", "workflow_rules")),
    22: ("notifications", ("notifications",)),
    27: ("packages", ("packages", "package_code")),
    42: ("modules", ("modules",)),
    50: ("automations", ("automations",)),
}
FINGERPRINT_SQL = (
    "select component_id, count(*) n, max(nvl(modified_at, created_at)) changed from comp_object_log "
    f"where component_id in ({', '.join(map(str, CHANGE_SOURCES))}) group by component_id"
)
REREAD_ON_CHANGE = ("invalid",)

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


def sources_file(alias: str) -> Path:
    return agent_dir("graph-sources") / f"{slugify(alias)}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load(alias: str) -> dict[str, Any] | None:
    return _read_json(graph_file(alias))


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


def _flag(value: Any) -> bool:
    return str(value) not in ("0", "", "None")


def _page_size(name: str) -> int:
    return CODE_PAGE if name.endswith("_code") else PAGE


def _package_bodies(sql: SqlReader) -> list[dict[str, Any]]:
    exported = components.export(sql.alias, "DB_PACKAGE", None, sql.cancel)
    return [
        {"DB_PACKAGE_ID": values["DB_PACKAGE_ID"], "BODY": values["DB_PACKAGE_BODY"]}
        for values in map(components.fields, exported)
    ]


EXPORTS: dict[str, Callable[[SqlReader], list[dict[str, Any]]]] = {"package_code": _package_bodies}


def _queries(sql: SqlReader) -> dict[str, str]:
    versioned = int(sql.page(VERSIONED_WORKFLOWS_SQL, 0, 1)[0]["N"]) > 0
    current = CURRENT_VERSION if versioned else EVERY_VERSION
    return {
        name: query.replace("{current}", current) if name in WORKFLOW_QUERIES else query
        for name, query in QUERIES.items()
    }


def _fingerprint(sql: SqlReader) -> dict[str, str]:
    rows = sql.page(FINGERPRINT_SQL, 0, len(CHANGE_SOURCES))
    return {str(row["COMPONENT_ID"]): f"{row['N']}@{row['CHANGED']}" for row in rows}


def _changed(before: dict[str, str], after: dict[str, str]) -> dict[str, tuple[str, ...]]:
    return {
        label: names
        for component, (label, names) in CHANGE_SOURCES.items()
        if before.get(str(component)) != after.get(str(component))
    }


def _read(
    sql: SqlReader, names: list[str], report: Callable[[str], None]
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    queries = _queries(sql)
    results: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    lock = threading.Lock()

    def fetch(name: str) -> None:
        try:
            rows = EXPORTS[name](sql) if name in EXPORTS else sql.rows(queries[name], _page_size(name))
        except (GraphError, components.ExportError) as exc:
            if name not in OPTIONAL or "Test SQL" in str(exc):
                raise
            with lock:
                warnings.append(f"{name}: {exc}")
            rows = []

        with lock:
            results[name] = rows
            report(f"Read {len(results)} of {len(names)} sources")

    with ThreadPoolExecutor(max_workers=QUERY_WORKERS) as pool:
        for future in [pool.submit(fetch, name) for name in names]:
            future.result()

    return results, warnings


_jobs: dict[str, dict[str, Any]] = {}
_checked: dict[str, int] = {}
_checked_at: dict[str, float] = {}
_written: set[str] = set()
_state_lock = threading.Lock()
_build_locks: dict[str, threading.Lock] = {}


def _build_lock(alias: str) -> threading.Lock:
    with _state_lock:
        return _build_locks.setdefault(alias, threading.Lock())


def _mark_checked(alias: str) -> None:
    with _state_lock:
        _checked[alias] = int(time.time() * 1000)
        _checked_at[alias] = time.monotonic()
        _written.discard(alias)


def note_write(alias: str) -> None:
    with _state_lock:
        _checked_at.pop(alias, None)
        _written.add(alias)


def _due(alias: str, graph: dict[str, Any]) -> bool:
    with _state_lock:
        if graph["source"] == SOURCE_EXPORT:
            return alias in _written
        last = _checked_at.get(alias)
        return last is None or time.monotonic() - last >= RECHECK_SECONDS


def _save(alias: str, fields: dict[str, Any], sources: dict[str, list[dict[str, Any]]] | None) -> dict[str, Any]:
    graph = {**fields, "instance": alias, "builtAt": int(time.time() * 1000)}
    if sources is not None:
        write_atomic(sources_file(alias), json.dumps(sources))
    write_atomic(graph_file(alias), json.dumps(graph))
    _mark_checked(alias)
    return graph


def _build(alias: str, host: str, cancel: Cancel, report: Callable[[str], None]) -> dict[str, Any]:
    try:
        allowed = access.ensure(alias)
    except access.AccessError as exc:
        raise GraphError(str(exc)) from None

    if allowed["testSql"]:
        sql = SqlReader(alias, cancel)
        report("Reading the configuration")
        fingerprint = _fingerprint(sql)
        results, warnings = _read(sql, [*EXPORTS, *QUERIES], report)
        report("Linking objects")
        fields = {**_assemble(results), "host": host, "source": SOURCE_SQL, "warnings": warnings}
        return _save(alias, {**fields, "fingerprint": fingerprint}, results)

    if allowed["export"]:
        try:
            linked, warnings = graph_export.build(alias, cancel, report)
        except (graph_export.ExportGraphError, components.ExportError) as exc:
            raise GraphError(str(exc)) from None
        return _save(alias, {**linked, "host": host, "source": SOURCE_EXPORT, "warnings": warnings}, None)

    raise NoAccess(NO_SOURCE.format(instance=alias))


def _refresh(
    graph: dict[str, Any], sources: dict[str, list[dict[str, Any]]], cancel: Cancel, report: Callable[[str], None]
) -> dict[str, Any]:
    alias = graph["instance"]
    sql = SqlReader(alias, cancel)
    report("Checking for changes")
    fingerprint = _fingerprint(sql)
    changed = _changed(graph["fingerprint"], fingerprint)
    if not changed:
        _mark_checked(alias)
        return graph

    report(f"Re-reading {', '.join(changed)}")
    names = [name for group in changed.values() for name in group] + list(REREAD_ON_CHANGE)
    fresh, warnings = _read(sql, names, report)
    kept = [w for w in graph["warnings"] if w.partition(":")[0] not in fresh]
    merged = {**sources, **fresh}
    report("Linking objects")
    fields = {**_assemble(merged), "host": graph["host"], "source": SOURCE_SQL, "warnings": kept + warnings}
    return _save(alias, {**fields, "fingerprint": fingerprint, "refreshed": list(changed)}, merged)


def _signed_in(instance: str) -> tuple[str, str]:
    found = find_instance(instance)
    if found is None:
        raise GraphError(f"Not signed in to {instance}.")
    return found["alias"], host_of(found["url"])


def build(instance: str, cancel: Cancel | None = None, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    alias, host = _signed_in(instance)
    with _build_lock(alias):
        return _build(alias, host, cancel or Cancel(), progress or (lambda _: None))


def sync(instance: str, cancel: Cancel | None = None, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    alias, host = _signed_in(instance)
    report = progress or (lambda _: None)
    with _build_lock(alias):
        graph = load(alias)
        sources = _read_json(sources_file(alias))
        if graph is None or (graph["source"] == SOURCE_SQL and sources is None):
            return _build(alias, host, cancel or Cancel(), report)
        if not _due(alias, graph):
            return graph
        if graph["source"] == SOURCE_EXPORT:
            return _build(alias, host, cancel or Cancel(), report)
        return _refresh(graph, sources, cancel or Cancel(), report)


def _add_nodes(b: Builder, r: dict[str, list[dict[str, Any]]]) -> None:
    for table, kind, id_column, name_column in _PLAIN_NODES:
        for row in r[table]:
            b.node(kind, row[id_column], row[name_column])
    for table, kind, id_column, name_column, enabled_column in _SWITCHABLE_NODES:
        for row in r[table]:
            b.node(kind, row[id_column], row[name_column], enabled=_flag(row.get(enabled_column)))
    for row in r["fields"]:
        b.node("field", row["CONFIG_FIELD_ID"], row["CONFIG_FIELD_NAME"], dataType=as_number(row.get("DATA_TYPE")))
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


def _add_key_edges(b: Builder, r: dict[str, list[dict[str, Any]]]) -> None:
    for table, source_kind, source_column, target_kind, target_column, kind in _KEY_EDGES:
        for row in r[table]:
            source = f"{source_kind}:{as_number(row.get(source_column))}"
            b.edge(source, f"{target_kind}:{as_number(row.get(target_column))}", kind)


def _add_code_edges(b: Builder, r: dict[str, list[dict[str, Any]]]) -> None:
    refs = Refs(b.nodes, b.edges)
    for table, kind, column in _CODE_SOURCES:
        for row in r[table]:
            refs.link(b, f"{kind}:{as_number(row[column])}", _code_text(row))
    for row in r["package_code"]:
        refs.link(b, f"db_package:{as_number(row['DB_PACKAGE_ID'])}", row["BODY"])


def _flag_invalid(b: Builder, r: dict[str, list[dict[str, Any]]]) -> None:
    for row in r["invalid"]:
        kind = INVALID_TYPES.get(as_number(row["COMPONENT_ID"]))
        node = b.nodes.get(f"{kind}:{as_number(row['ENTITY_ID'])}") if kind else None
        if node is not None:
            node["invalid"] = True


def _assemble(r: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    b = Builder()
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
    number = as_number(text.split(":")[-1])
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


def status(alias: str) -> dict[str, Any]:
    with _state_lock:
        job = dict(_jobs.get(alias, {}))
        checked = _checked.get(alias)
    if job.get("state") == "building":
        return job

    graph = load(alias)
    if graph is None:
        return {"state": "none", **job}

    built = {
        "builtAt": graph["builtAt"],
        "checkedAt": checked or graph["builtAt"],
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "source": graph["source"],
        "refreshed": graph.get("refreshed", []),
    }
    return {"state": "ready", **built, **job}


def _start(alias: str, work: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    with _state_lock:
        if _jobs.get(alias, {}).get("state") == "building":
            return dict(_jobs[alias])
        _jobs[alias] = {"state": "building", "step": "Starting"}

    def progress(step: str) -> None:
        with _state_lock:
            _jobs[alias] = {"state": "building", "step": step}

    def run() -> None:
        try:
            work(alias, progress=progress)
            outcome: dict[str, Any] = {}
        except Exception as exc:
            outcome = {"state": "error", "error": str(exc) or type(exc).__name__}

        with _state_lock:
            _jobs[alias] = outcome

    threading.Thread(target=run, daemon=True, name=f"graph-{alias}").start()
    return status(alias)


def start_build(alias: str) -> dict[str, Any]:
    return _start(alias, build)


def start_sync(alias: str) -> dict[str, Any]:
    graph = load(alias)
    if graph is None or not _due(alias, graph):
        return status(alias)
    return _start(alias, sync)
