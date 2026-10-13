from __future__ import annotations

import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ov.agent.engine.cancel import Cancel
from ov.agent.instances import components
from ov.agent.instances.graph import CODE_CHUNKS, CODE_PAGE, PAGE_WORKERS, GraphError, SqlReader, load
from ov.agent.instances.ovproc import find_instance

CHUNK = 1000
MAX_CHARS = 400_000
CACHE_SIZE = 200
ACTIVITY_ROWS = 10
LONG_SYNC_LINES = 250

_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_cache_lock = threading.Lock()


class ExplorerError(Exception):
    pass


def _reader(alias: str) -> SqlReader:
    if find_instance(alias) is None:
        raise ExplorerError(f"Not signed in to {alias}.")
    return SqlReader(alias, Cancel())


def _chunks(column: str, offset: int) -> str:
    return ", ".join(f"dbms_lob.substr({column}, {CHUNK}, {offset + i * CHUNK}) c{i}" for i in range(CODE_CHUNKS))


def _joined(row: dict[str, Any]) -> str:
    return "".join(row[f"C{i}"] or "" for i in range(CODE_CHUNKS))


def _clob(sql: SqlReader, table: str, column: str, where: str) -> str:
    def read(offset: int, with_length: bool = False) -> dict[str, Any]:
        columns = _chunks(column, offset)
        if with_length:
            columns = f"dbms_lob.getlength({column}) n, {columns}"
        rows = sql.page(f"select {columns} from {table} where {where}", 0, 1)
        if not rows:
            raise ExplorerError(f"No {table} row where {where}.")
        return rows[0]

    first = read(1, with_length=True)
    window = CHUNK * CODE_CHUNKS
    length = min(int(first["N"] or 0), MAX_CHARS)
    offsets = range(1 + window, length + 1, window)
    if not offsets:
        return _joined(first)

    with ThreadPoolExecutor(max_workers=PAGE_WORKERS) as pool:
        return _joined(first) + "".join(_joined(row) for row in pool.map(read, offsets))


def _clobs(sql: SqlReader, table: str, where: str, columns: dict[str, str]) -> list[dict[str, str]]:
    with ThreadPoolExecutor(max_workers=len(columns)) as pool:
        codes = pool.map(lambda column: _clob(sql, table, column, where), columns.values())
        return [{"title": title, "code": code} for title, code in zip(columns, codes, strict=True)]


def _pieces(sql: SqlReader, query: str, code_column: str) -> list[dict[str, str]]:
    rows = sql.rows(query.replace("{code}", _chunks(code_column, 1)), CODE_PAGE)
    return [{"title": str(row["NAME"] or "SQL"), "code": _joined(row)} for row in rows if _joined(row).strip()]


_CLOB_SECTIONS: dict[str, tuple[str, str, dict[str, str]]] = {
    "rule": ("rule", "rule_id", {"Rule SQL": "sql_text"}),
    "field": ("config_field", "config_field_id", {"SQL": "sql_query", "Default value SQL": "default_value_sql"}),
    "notification": ("notif", "notif_id", {"Trackor SQL": "trackor_sql", "User SQL": "user_sql"}),
}

_PIECE_SECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "import": (
        ("select entity_name name, {code} from imp_entity where imp_spec_id = {ref}", "sql_text"),
        ("select data_map_name name, {code} from imp_data_map where imp_spec_id = {ref}", "sql_text"),
    ),
    "report": (
        (
            "select sql_name name, {code} from report_sql where report_file_id = {ref} order by order_number",
            "sql_text",
        ),
    ),
    "workflow": (("select step_name name, {code} from wf_template_step where wf_template_id = {ref}", "plsql_block"),),
    "automation": (
        (
            "select 'Filter ' || order_number name, {code} from autom_filter where autom_id = {ref} "
            "order by order_number",
            "filter_sql",
        ),
    ),
}


_EXPORTED_SECTIONS: dict[str, tuple[str, dict[str, str]]] = {
    "db_package": ("DB_PACKAGE", {"Body": "DB_PACKAGE_BODY", "Spec": "DB_PACKAGE_SPEC"}),
}


def _exported(sql: SqlReader, kind: str, ref: int) -> list[dict[str, str]]:
    component_type, columns = _EXPORTED_SECTIONS[kind]
    found = components.export(sql.alias, component_type, [ref], sql.cancel)
    if not found:
        raise ExplorerError(f"The component export returned no {kind} {ref}.")

    values = components.fields(found[0])
    return [{"title": title, "code": values[tag]} for title, tag in columns.items()]


def _sections(sql: SqlReader, kind: str, ref: int) -> list[dict[str, str]]:
    if kind in _EXPORTED_SECTIONS:
        return _exported(sql, kind, ref)

    if kind in _CLOB_SECTIONS:
        table, key, columns = _CLOB_SECTIONS[kind]
        return _clobs(sql, table, f"{key} = {ref}", columns)

    return [
        piece
        for query, column in _PIECE_SECTIONS.get(kind, ())
        for piece in _pieces(sql, query.replace("{ref}", str(ref)), column)
    ]


def _cached(key: tuple[str, str]) -> dict[str, Any] | None:
    with _cache_lock:
        if key not in _cache:
            return None
        _cache.move_to_end(key)
        return _cache[key]


def _remember(key: tuple[str, str], result: dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def source(alias: str, node_id: str) -> dict[str, Any]:
    kind, _, ref_text = node_id.partition(":")
    if not ref_text.isdigit():
        raise ExplorerError(f"Bad object id: {node_id}")

    key = (alias, node_id)
    cached = _cached(key)
    if cached is not None:
        return cached

    sql = _reader(alias)
    try:
        sections = [s for s in _sections(sql, kind, int(ref_text)) if s["code"].strip()]
    except (GraphError, components.ExportError) as exc:
        raise ExplorerError(str(exc)) from exc

    graph = load(alias)
    nodes = graph["nodes"] if graph else []
    node = next((n for n in nodes if n["id"] == node_id), {"type": kind})
    known = {n["ref"] for n in nodes}
    result = {"sections": [{**section, "hints": hints(section["code"], node, known)} for section in sections]}
    _remember(key, result)
    return result


def forget(alias: str) -> None:
    with _cache_lock:
        for key in [k for k in _cache if k[0] == alias]:
            del _cache[key]


ACTIVITY: dict[str, str] = {
    "rule": (
        "select * from ("
        "select to_char(q.created_ts, 'YYYY-MM-DD HH24:MI') ts, 'Queue error' status, "
        "null runtime, dbms_lob.substr(q.exception_message, 600, 1) message "
        "from rule_queue q where q.rule_id = {ref} and q.rule_queue_status_id = 2 "
        "union all "
        "select to_char(p.start_date, 'YYYY-MM-DD HH24:MI') ts, s.status, p.runtime, "
        "p.error_message message from rule_run rr join process p on p.process_id = rr.process_id "
        "join process_status s on s.process_status_id = p.status_id where rr.rule_id = {ref}"
        ") order by ts desc"
    ),
    "import": (
        "select to_char(p.start_date, 'YYYY-MM-DD HH24:MI') ts, s.status, p.runtime, "
        "p.error_message message from imp_run r join process p on p.process_id = r.process_id "
        "join process_status s on s.process_status_id = p.status_id "
        "where r.imp_spec_id = {ref} order by p.start_date desc nulls last"
    ),
    "report": (
        "select to_char(p.start_date, 'YYYY-MM-DD HH24:MI') ts, s.status, p.runtime, "
        "p.error_message message from report_run r join process p on p.process_id = r.process_id "
        "join process_status s on s.process_status_id = p.status_id "
        "where r.report_file_id = {ref} order by p.start_date desc nulls last"
    ),
    "module": (
        "select to_char(p.start_date, 'YYYY-MM-DD HH24:MI') ts, s.status, p.runtime, "
        "p.error_message message from module_run r join process p on p.process_id = r.process_id "
        "join process_status s on s.process_status_id = p.status_id "
        "where r.module_id = {ref} order by p.start_date desc nulls last"
    ),
    "automation": (
        "select to_char(p.start_date, 'YYYY-MM-DD HH24:MI') ts, s.status, p.runtime, "
        "p.error_message message from autom_run ar "
        "join autom_action aa on aa.autom_action_id = ar.autom_action_id "
        "join autom_filter f on f.autom_filter_id = aa.autom_filter_id "
        "join process p on p.process_id = ar.process_id "
        "join process_status s on s.process_status_id = p.status_id "
        "where f.autom_id = {ref} order by p.start_date desc nulls last"
    ),
}


def activity(alias: str, node_id: str) -> list[dict[str, Any]]:
    kind, _, ref_text = node_id.partition(":")
    if not ref_text.isdigit():
        raise ExplorerError(f"Bad object id: {node_id}")

    query = ACTIVITY.get(kind)
    if query is None:
        return []

    try:
        rows = _reader(alias).page(query.format(ref=int(ref_text)), 0, ACTIVITY_ROWS)
    except GraphError as exc:
        raise ExplorerError(str(exc)) from exc

    return [
        {"ts": row["TS"], "status": row["STATUS"], "runtime": row["RUNTIME"], "message": row["MESSAGE"]} for row in rows
    ]


_LOOP_START = re.compile(r"\b(for\b.*\bloop|while\b.*\bloop|loop)\s*$", re.IGNORECASE)
_LOOP_END = re.compile(r"\bend\s+loop\b", re.IGNORECASE)
_LOOKUP = re.compile(r"\b(util|rpt|pkg_config_field_rpt)\s*\.\s*getval\w*\s*\(|\bselect\b", re.IGNORECASE)
_SELECT_INTO = re.compile(r"\bselect\b(?:(?!\bfrom\b).)*?\binto\b", re.IGNORECASE | re.DOTALL)
_AGGREGATE = re.compile(r"\b(max|min|count|sum|avg)\s*\(", re.IGNORECASE)
_LITERAL = re.compile(r"[=<>]\s*(\d{3,})\b(?!\s*/\*)")
_UPDATE_TRIGGERS = ("trackor updated", "trackor created/updated", "trackor created or updated")
_SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}

_NESTED_LOOPS = (
    "warn",
    "Nested loops",
    "A loop inside a loop runs its body rows x rows times. A single query with a join is usually much faster.",
)
_QUERY_IN_LOOP = (
    "warn",
    "Query inside a loop",
    "This runs once per row. Join the data into the loop's cursor instead of looking it up row by row.",
)
_LINE_CHECKS = (
    (
        re.compile(r"\bselect\s+\*", re.IGNORECASE),
        "info",
        "SELECT *",
        "Name the columns you need: it reads less and does not break when columns are added.",
    ),
    (
        re.compile(r"^\s*(commit|rollback)\s*;", re.IGNORECASE),
        "error",
        "COMMIT or ROLLBACK in a rule",
        "Rules run inside the platform's transaction. Committing here can save half-finished work or break the caller.",
    ),
    (
        re.compile(r"\bexecute\s+immediate\b[^;]*\|\|", re.IGNORECASE),
        "warn",
        "Dynamic SQL built from strings",
        "Concatenated SQL is re-parsed every time and can break on quotes. Use bind variables with EXECUTE "
        "IMMEDIATE ... USING.",
    ),
    (
        re.compile(r"\bwhen\s+others\s+then\s+null\s*;", re.IGNORECASE),
        "error",
        "Errors are silently ignored",
        "WHEN OTHERS THEN NULL hides every failure, so problems show up later as wrong data. Handle the specific "
        "exception or let it raise.",
    ),
    (
        re.compile(r"\bdbms_output\.", re.IGNORECASE),
        "info",
        "DBMS_OUTPUT",
        "Output written with DBMS_OUTPUT is not shown anywhere when a rule runs.",
    ),
)


def _strip_comments(line: str) -> str:
    return re.sub(r"--.*$", "", re.sub(r"/\*.*?\*/", "", line))


def _hint(line: int, severity: str, title: str, detail: str) -> dict[str, Any]:
    return {"line": line, "severity": severity, "title": title, "detail": detail}


def _loop_hints(lines: list[str]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    depth = 0
    for number, line in enumerate(lines, 1):
        ends = bool(_LOOP_END.search(line))
        starts = not ends and bool(_LOOP_START.search(line))
        depth = max(0, depth - 1) if ends else depth + starts
        if starts and depth == 2 and "nested" not in found:
            found["nested"] = _hint(number, *_NESTED_LOOPS)
        if depth and not starts and _LOOKUP.search(line) and "lookup" not in found:
            found["lookup"] = _hint(number, *_QUERY_IN_LOOP)
    return list(found.values())


def _unknown_literal(line: str, known: set[int]) -> str | None:
    if "id." in line.lower():
        return None
    return next((m.group(1) for m in _LITERAL.finditer(line) if int(m.group(1)) not in known), None)


def _line_hints(lines: list[str], known: set[int]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        found += [_hint(number, *check) for pattern, *check in _LINE_CHECKS if pattern.search(line)]
        literal = _unknown_literal(line, known)
        if literal:
            found.append(
                _hint(
                    number,
                    "info",
                    "Hard-coded value",
                    f"{literal} is hard-coded. If it is a config id, an object reference such as "
                    "id.<type>.cf.<field> survives renumbering and copies between instances.",
                )
            )
    return found


def _select_into_hints(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    if "no_data_found" in lowered or "when others" in lowered:
        return []

    match = next((m for m in _SELECT_INTO.finditer(text) if not _AGGREGATE.search(m.group(0))), None)
    if match is None:
        return []

    return [
        _hint(
            text[: match.start()].count("\n") + 1,
            "warn",
            "SELECT INTO can fail with no data",
            "If no row matches, this raises NO_DATA_FOUND and the whole rule fails. Use MAX(...), a cursor, or "
            "handle NO_DATA_FOUND.",
        )
    ]


def _rule_hints(node: dict[str, Any], line_count: int) -> list[dict[str, Any]]:
    if node["type"] != "rule":
        return []

    found = []
    trigger = str(node.get("trigger") or "").lower()
    if any(t in trigger for t in _UPDATE_TRIGGERS) and not node.get("filtered"):
        found.append(
            _hint(
                1,
                "warn",
                "Runs on every update",
                "This rule fires on every change to the trackor and has no filter. A filter or a field-update "
                "trigger avoids running it when it cannot matter.",
            )
        )
    if not node.get("async") and line_count > LONG_SYNC_LINES:
        found.append(
            _hint(
                1,
                "info",
                "Long rule runs while the user waits",
                f"{line_count} lines run synchronously. If the result is not needed immediately, making the rule "
                "async keeps saves fast.",
            )
        )
    return found


def hints(code: str, node: dict[str, Any], known: set[int] | None = None) -> list[dict[str, Any]]:
    lines = [_strip_comments(line) for line in code.replace("\r\n", "\n").split("\n")]
    found = [
        *_loop_hints(lines),
        *_line_hints(lines, known or set()),
        *_select_into_hints("\n".join(lines)),
        *_rule_hints(node, len(lines)),
    ]
    return sorted(found, key=lambda h: (_SEVERITY_ORDER[h["severity"]], h["line"]))
