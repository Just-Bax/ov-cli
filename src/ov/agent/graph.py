from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..paths import agent_dir, slugify, write_atomic
from .cancel import Cancel
from .ovproc import find_instance, host_of, run_ov

PAGE = 1000
# Code text is large; a full page of it makes the Test SQL endpoint fail.
CODE_PAGE = 200
MAX_PAGES = 60
PAGE_WORKERS = 4
CODE_CHUNKS = 10
SQL_TIMEOUT_SECONDS = 180

# INVALID_OBJECT.COMPONENT_ID -> node type.
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

FORMS = {
    "trackor_type": "/admin/trackortypes/Form.do?id=",
    "field": "/admin/configfields/Form.do?id=",
    "rule": "/admin/rules/Form.do?id=",
    "automation": "/admin/automation/Form.do?id=",
    "import": "/admin/configimport/Form.do?id=",
    "report": "/admin/reports/Form.do?id=",
    "notification": "/admin/notifications/Form.do?id=",
    "workflow": "/admin/wftemplate/Form.do?id=",
    "module": "/admin/module/Form.do?id=",
    "db_package": "/admin/dbpackage/Form.do?id=",
}

# Only clean references count as links: config ids, quoted names, id.* object references
# and package calls. Bare words are too often columns or variables that share a field's name.
_NUMBER = re.compile(r"\b\d{6,12}\b")
_QUOTED = re.compile(r"(['\"])([A-Za-z][A-Za-z0-9_$#]{2,})\1")
# Same pattern PKG_OBJREF_UTIL uses to find references in code.
_OBJREF = re.compile(r"\bid\.([A-Za-z0-9_.]+)", re.IGNORECASE)
_CALL = re.compile(r"\b([A-Za-z][A-Za-z0-9_$#]*)\s*\.\s*[A-Za-z]")
OBJREF_KINDS = {"imp": "import", "rpt": "report", "wf": "workflow"}
# Package bodies are read in windows of CODE_CHUNKS x 1000 characters.
PACKAGE_WINDOWS = 40


class GraphError(Exception):
    pass


# 1000-character pieces in separate columns: multi-byte text would pass the 4000-byte SQL limit.
def _code(column: str, start: str = "1") -> str:
    return ", ".join(
        f"dbms_lob.substr({column}, 1000, {start} + {i * 1000}) code{i}" for i in range(CODE_CHUNKS)
    )


def _code_text(row: dict[str, Any]) -> str:
    return "".join(str(row.get(f"CODE{i}") or "") for i in range(CODE_CHUNKS))


# Each query is (node type or edge set name, SQL). Only columns verified against the platform DDL.
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
    "import_code": "select imp_spec_id, sql_text code0 from imp_data_map "
    "where sql_text is not null",
    "reports": "select report_file_id, report_name from report_files",
    "report_code": f"select report_file_id, {_code('sql_text')} from report_sql",
    "notifications": "select notif_id, notif_name, is_enabled, trackor_type_id from notif",
    "workflows": "select wf_template_id, template_name from wf_template "
    "where is_current_version = 1",
    "workflow_rules": "select s.wf_template_id, s.rule_id from wf_template_step s "
    "join wf_template t on t.wf_template_id = s.wf_template_id "
    "where t.is_current_version = 1 and s.rule_id is not null",
    "modules": "select module_id, module_name, is_enabled from module "
    "where nvl(is_archived, 0) = 0",
    "invalid": "select component_id, entity_id from invalid_object",
    "packages": "select db_package_id, db_package_name from db_package",
    "package_code": "select p.db_package_id, w.n, "
    + _code("p.db_package_body", f"1 + w.n * {CODE_CHUNKS * 1000}")
    + f" from db_package p join (select level - 1 n from dual connect by level <= "
    f"{PACKAGE_WINDOWS}) w on w.n * {CODE_CHUNKS * 1000} < "
    "nvl(dbms_lob.getlength(p.db_package_body), 0) order by p.db_package_id, w.n",
}

# The graph is still useful without these, e.g. on instances without Vizion Hub.
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


def graph_file(alias: str) -> Path:
    return agent_dir("graphs") / f"{slugify(alias)}.json"


def load(alias: str) -> dict[str, Any] | None:
    path = graph_file(alias)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


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
                "sql",
                "check-sql-and-return-result-set",
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
        if result.code == 6 or "TEST_SQL" in result.message:
            raise GraphError("Building a map needs the Test SQL privilege on this instance.")
        if result.code != 0:
            raise GraphError(result.message[:400] or f"ov exited {result.code}")
        data = json.loads(result.stdout)
        if data.get("status") != "SUCCESS":
            raise GraphError(str(data.get("error_message") or "SQL failed"))
        columns = [c.upper() for c in data.get("columns") or []]
        return [dict(zip(columns, row.get("cells", []), strict=False)) for row in data["rows"]]

    def count(self, sql: str) -> int:
        rows = self.page(f"select count(*) n from ({sql})", 0, 1)
        return int(rows[0]["N"]) if rows else 0

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
    return str(value or "0") not in ("0", "", "None")


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
    # id.<type>.tt, and the type behind id.<type>.rel.* or id.<type>.class.*.
    return objrefs.get(f"id.{parts[0]}.tt") if parts else None


class _Refs:
    def __init__(self, nodes: dict[str, dict[str, Any]], edges: set) -> None:
        ids: dict[int, str | None] = {}
        for node in nodes.values():
            ids[node["ref"]] = None if node["ref"] in ids else node["id"]
        self.ids = {k: v for k, v in ids.items() if v is not None}
        names: dict[str, str | None] = {}
        for node in nodes.values():
            if node["type"] in ("field", "trackor_type", "db_package"):
                key = node["name"].upper()
                # A name shared by two objects cannot be resolved from code text.
                names[key] = None if key in names else node["id"]
        self.names = {k: v for k, v in names.items() if v is not None and len(k) > 3}
        self.packages = {
            n["name"].upper(): n["id"] for n in nodes.values() if n["type"] == "db_package"
        }
        owner = {s: t for s, t, k, _ in edges if k == "field_of"}
        self.objrefs: dict[str, str] = {}
        for node in nodes.values():
            name = objref_key(node["name"])
            if node["type"] == "trackor_type":
                self.objrefs[f"id.{name}.tt"] = node["id"]
            elif node["type"] == "field" and owner.get(node["id"]) in nodes:
                tt = objref_key(nodes[owner[node["id"]]]["name"])
                self.objrefs[f"id.{tt}.cf.{name}"] = node["id"]
            else:
                prefix = next((k for k, v in OBJREF_KINDS.items() if v == node["type"]), None)
                if prefix:
                    self.objrefs[f"id.{prefix}.{name}"] = node["id"]

    def link(self, builder: _Builder, source: str, text: str) -> None:
        targets = {self.ids[int(n)] for n in _NUMBER.findall(text) if int(n) in self.ids}
        targets |= {
            self.names[q.upper()] for _, q in _QUOTED.findall(text) if q.upper() in self.names
        }
        for ref in _OBJREF.findall(text):
            found = objref_target(ref, self.objrefs)
            if found:
                targets.add(found)
        for name in _CALL.findall(text):
            package = self.packages.get(name.upper())
            if package:
                targets.add(package)
        for target in targets:
            kind = "calls" if target.startswith("db_package:") else "uses"
            builder.edge(source, target, kind, code=True)


def build(
    instance: str, cancel: Cancel | None = None, progress: Callable[[str], None] | None = None
) -> dict[str, Any]:
    found = find_instance(instance)
    if found is None:
        raise GraphError(f"Not signed in to {instance}.")
    cancel = cancel or Cancel()
    sql = SqlReader(found["alias"], cancel)
    report = progress or (lambda _: None)

    results: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    lock = threading.Lock()

    def fetch(name: str) -> None:
        try:
            rows = sql.rows(QUERIES[name], CODE_PAGE if name.endswith("_code") else PAGE)
        except GraphError as exc:
            if name not in OPTIONAL or "Test SQL" in str(exc):
                raise
            with lock:
                warnings.append(f"{name}: {exc}")
            rows = []
        with lock:
            results[name] = rows
            report(f"Read {len(results)} of {len(QUERIES)} sources")

    report("Reading the configuration")
    with ThreadPoolExecutor(max_workers=6) as pool:
        for future in [pool.submit(fetch, name) for name in QUERIES]:
            future.result()

    report("Linking objects")
    graph = _assemble(results)
    graph.update(
        {
            "instance": found["alias"],
            "host": host_of(found["url"]),
            "builtAt": int(time.time() * 1000),
            "warnings": warnings,
        }
    )
    write_atomic(graph_file(found["alias"]), json.dumps(graph))
    return graph


def _assemble(r: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    b = _Builder()
    for row in r["trackor_types"]:
        b.node("trackor_type", row["XITOR_TYPE_ID"], row["XITOR_TYPE"])
    for row in r["fields"]:
        b.node(
            "field",
            row["CONFIG_FIELD_ID"],
            row["CONFIG_FIELD_NAME"],
            dataType=_num(row.get("DATA_TYPE")),
        )
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
    for row in r["automations"]:
        b.node("automation", row["AUTOM_ID"], row["AUTOM_NAME"], enabled=_flag(row.get("ENABLED")))
    for row in r["imports"]:
        b.node("import", row["IMP_SPEC_ID"], row["NAME"])
    for row in r["reports"]:
        b.node("report", row["REPORT_FILE_ID"], row["REPORT_NAME"])
    for row in r["notifications"]:
        b.node(
            "notification",
            row["NOTIF_ID"],
            row["NOTIF_NAME"],
            enabled=_flag(row.get("IS_ENABLED")),
        )
    for row in r["workflows"]:
        b.node("workflow", row["WF_TEMPLATE_ID"], row["TEMPLATE_NAME"])
    for row in r["modules"]:
        b.node("module", row["MODULE_ID"], row["MODULE_NAME"], enabled=_flag(row.get("IS_ENABLED")))
    for row in r["packages"]:
        b.node("db_package", row["DB_PACKAGE_ID"], row["DB_PACKAGE_NAME"])

    for row in r["relations"]:
        b.edge(
            f"trackor_type:{_num(row['PARENT_TYPE_ID'])}",
            f"trackor_type:{_num(row['CHILD_TYPE_ID'])}",
            "parent_of",
        )
    for row in r["fields"]:
        field = f"field:{_num(row['CONFIG_FIELD_ID'])}"
        b.edge(field, f"trackor_type:{_num(row.get('XITOR_TYPE_ID'))}", "field_of")
        if row.get("OBJ_XITOR_TYPE_ID"):
            b.edge(field, f"trackor_type:{_num(row['OBJ_XITOR_TYPE_ID'])}", "points_to")
    for row in r["rules"]:
        if row.get("PRIMARY_TRACKOR_TYPE_ID"):
            b.edge(
                f"rule:{_num(row['RULE_ID'])}",
                f"trackor_type:{_num(row['PRIMARY_TRACKOR_TYPE_ID'])}",
                "on",
            )
    for row in r["rule_bindings"]:
        b.edge(f"rule:{_num(row['RULE_ID'])}", f"field:{_num(row['ID_NUM'])}", "triggered_by")
    for row in r["automations"]:
        b.edge(
            f"automation:{_num(row['AUTOM_ID'])}",
            f"trackor_type:{_num(row.get('TRACKOR_TYPE_ID'))}",
            "on",
        )
    for row in r["import_entities"]:
        b.edge(
            f"import:{_num(row['IMP_SPEC_ID'])}",
            f"trackor_type:{_num(row.get('XITOR_TYPE_ID'))}",
            "loads",
        )
    for row in r["notifications"]:
        b.edge(
            f"notification:{_num(row['NOTIF_ID'])}",
            f"trackor_type:{_num(row.get('TRACKOR_TYPE_ID'))}",
            "on",
        )
    for row in r["workflow_rules"]:
        b.edge(
            f"workflow:{_num(row['WF_TEMPLATE_ID'])}",
            f"rule:{_num(row['RULE_ID'])}",
            "runs",
        )

    refs = _Refs(b.nodes, b.edges)
    for key, kind, column in (
        ("rule_code", "rule", "RULE_ID"),
        ("import_code", "import", "IMP_SPEC_ID"),
        ("report_code", "report", "REPORT_FILE_ID"),
    ):
        for row in r.get(key, []):
            refs.link(b, f"{kind}:{_num(row[column])}", _code_text(row))
    bodies: dict[int | None, list[tuple[int, str]]] = {}
    for row in r.get("package_code", []):
        bodies.setdefault(_num(row["DB_PACKAGE_ID"]), []).append(
            (_num(row.get("N")) or 0, _code_text(row))
        )
    for package, windows in bodies.items():
        refs.link(b, f"db_package:{package}", "".join(text for _, text in sorted(windows)))

    for row in r["invalid"]:
        kind = INVALID_TYPES.get(_num(row.get("COMPONENT_ID")) or -1)
        node = b.nodes.get(f"{kind}:{_num(row.get('ENTITY_ID'))}") if kind else None
        if node is not None:
            node["invalid"] = True

    edges = [
        {"source": s, "target": t, "kind": k, **({"code": True} if c else {})}
        for s, t, k, c in sorted(b.edges)
    ]
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
        n
        for n in graph["nodes"]
        if n["name"].lower() == text or n["id"] == text or (number and n["ref"] == number)
    ]
    if exact:
        return exact
    return [n for n in graph["nodes"] if text in n["name"].lower()][:20]


# Edge labels read as "<source> <label> <target>" and, reversed, "<target> <reverse> <source>".
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


def describe(graph: dict[str, Any], node: dict[str, Any], limit: int = 60) -> str:
    groups: dict[str, list[str]] = {}
    for direction, kind, other in neighbors(graph, node["id"]):
        forward, backward = LABELS.get(kind, (kind, kind))
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
    graph = load(alias) if job.get("state") != "building" else None
    if job.get("state") == "building":
        return job
    built = (
        {"builtAt": graph["builtAt"], "nodes": len(graph["nodes"]), "edges": len(graph["edges"])}
        if graph
        else {}
    )
    return {"state": job.get("state") or ("ready" if graph else "none"), **built, **job}


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
