from __future__ import annotations

import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .cancel import Cancel
from .graph import CODE_CHUNKS, PAGE_WORKERS, GraphError, SqlReader, load
from .ovproc import find_instance

CHUNK = 1000
MAX_CHARS = 400_000
CACHE_SIZE = 200
ACTIVITY_ROWS = 10

_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_cache_lock = threading.Lock()


class ExplorerError(Exception):
    pass


def _reader(alias: str) -> SqlReader:
    if find_instance(alias) is None:
        raise ExplorerError(f"Not signed in to {alias}.")
    return SqlReader(alias, Cancel())


def _clob(sql: SqlReader, table: str, column: str, where: str) -> str:
    window = CHUNK * CODE_CHUNKS

    def read(offset: int, with_length: bool = False) -> dict[str, Any]:
        columns = ", ".join(
            f"dbms_lob.substr({column}, {CHUNK}, {offset + i * CHUNK}) c{i}"
            for i in range(CODE_CHUNKS)
        )
        if with_length:
            columns = f"dbms_lob.getlength({column}) n, {columns}"
        rows = sql.page(f"select {columns} from {table} where {where}", 0, 1)
        return rows[0] if rows else {}

    def text(row: dict[str, Any]) -> str:
        return "".join(str(row.get(f"C{i}") or "") for i in range(CODE_CHUNKS))

    first = read(1, with_length=True)
    length = min(int(first.get("N") or 0), MAX_CHARS)
    offsets = range(1 + window, length + 1, window)
    if not offsets:
        return text(first)
    with ThreadPoolExecutor(max_workers=PAGE_WORKERS) as pool:
        return text(first) + "".join(text(row) for row in pool.map(read, offsets))


def _clobs(sql: SqlReader, table: str, where: str, columns: dict[str, str]) -> list[dict[str, str]]:
    with ThreadPoolExecutor(max_workers=len(columns)) as pool:
        codes = pool.map(lambda column: _clob(sql, table, column, where), columns.values())
        return [{"title": title, "code": code} for title, code in zip(columns, codes)]


def _pieces(sql: SqlReader, query: str, title: str, code_column: str) -> list[dict[str, str]]:
    columns = ", ".join(
        f"dbms_lob.substr({code_column}, {CHUNK}, {1 + i * CHUNK}) c{i}" for i in range(CODE_CHUNKS)
    )
    rows = sql.rows(query.format(code=columns), 200)
    parts = []
    for row in rows:
        code = "".join(str(row.get(f"C{i}") or "") for i in range(CODE_CHUNKS))
        if code.strip():
            parts.append({"title": str(row.get(title) or "SQL"), "code": code})
    return parts


def _sections(sql: SqlReader, kind: str, ref: int) -> list[dict[str, str]]:
    if kind == "rule":
        return [{"title": "Rule SQL", "code": _clob(sql, "rule", "sql_text", f"rule_id = {ref}")}]
    if kind == "db_package":
        return _clobs(
            sql,
            "db_package",
            f"db_package_id = {ref}",
            {"Body": "db_package_body", "Spec": "db_package_spec"},
        )
    if kind == "field":
        return _clobs(
            sql,
            "config_field",
            f"config_field_id = {ref}",
            {"SQL": "sql_query", "Default value SQL": "default_value_sql"},
        )
    if kind == "import":
        return _pieces(
            sql,
            "select entity_name name, {code} from imp_entity where imp_spec_id = " + str(ref),
            "NAME",
            "sql_text",
        ) + _pieces(
            sql,
            "select data_map_name name, {code} from imp_data_map where imp_spec_id = " + str(ref),
            "NAME",
            "sql_text",
        )
    if kind == "report":
        return _pieces(
            sql,
            "select sql_name name, {code} from report_sql where report_file_id = "
            + str(ref)
            + " order by order_number",
            "NAME",
            "sql_text",
        )
    if kind == "workflow":
        return _pieces(
            sql,
            "select step_name name, {code} from wf_template_step where wf_template_id = "
            + str(ref),
            "NAME",
            "plsql_block",
        )
    if kind == "automation":
        return _pieces(
            sql,
            "select 'Filter ' || order_number name, {code} from autom_filter where autom_id = "
            + str(ref)
            + " order by order_number",
            "NAME",
            "filter_sql",
        )
    if kind == "notification":
        return _clobs(
            sql,
            "notif",
            f"notif_id = {ref}",
            {"Trackor SQL": "trackor_sql", "User SQL": "user_sql"},
        )
    return []


def source(alias: str, node_id: str) -> dict[str, Any]:
    kind, _, ref_text = node_id.partition(":")
    if not ref_text.isdigit():
        raise ExplorerError(f"Bad object id: {node_id}")
    key = (alias, node_id)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    sql = _reader(alias)
    try:
        sections = [s for s in _sections(sql, kind, int(ref_text)) if s["code"].strip()]
    except GraphError as exc:
        raise ExplorerError(str(exc)) from exc

    graph = load(alias)
    node = next((n for n in graph["nodes"] if n["id"] == node_id), None) if graph else None
    known = {n["ref"] for n in graph["nodes"]} if graph else set()
    result = {
        "sections": [
            {**section, "hints": hints(section["code"], node or {"type": kind}, known)}
            for section in sections
        ]
    }
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def forget(alias: str) -> None:
    with _cache_lock:
        for key in [k for k in _cache if k[0] == alias]:
            del _cache[key]


# Verified against the platform DDL: every run log ends in PROCESS (status, dates, errors).
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
    query = ACTIVITY.get(kind)
    if query is None or not ref_text.isdigit():
        return []
    try:
        rows = _reader(alias).page(query.format(ref=int(ref_text)), 0, ACTIVITY_ROWS)
    except GraphError as exc:
        raise ExplorerError(str(exc)) from exc
    return [
        {
            "ts": row.get("TS"),
            "status": row.get("STATUS"),
            "runtime": row.get("RUNTIME"),
            "message": row.get("MESSAGE"),
        }
        for row in rows
    ]


_LOOP_START = re.compile(r"\b(for\b.*\bloop|while\b.*\bloop|loop)\s*$", re.IGNORECASE)
_LOOP_END = re.compile(r"\bend\s+loop\b", re.IGNORECASE)
_LOOKUP = re.compile(
    r"\b(util|rpt|pkg_config_field_rpt)\s*\.\s*getval\w*\s*\(|\bselect\b", re.IGNORECASE
)
_SELECT_STAR = re.compile(r"\bselect\s+\*", re.IGNORECASE)
_SELECT_INTO = re.compile(r"\bselect\b(?:(?!\bfrom\b).)*?\binto\b", re.IGNORECASE | re.DOTALL)
_AGGREGATE = re.compile(r"\b(max|min|count|sum|avg)\s*\(", re.IGNORECASE)
_COMMIT = re.compile(r"^\s*(commit|rollback)\s*;", re.IGNORECASE)
_DYNAMIC = re.compile(r"\bexecute\s+immediate\b[^;]*\|\|", re.IGNORECASE)
_SWALLOW = re.compile(r"\bwhen\s+others\s+then\s+null\s*;", re.IGNORECASE)
_LITERAL = re.compile(r"[=<>]\s*(\d{3,})\b(?!\s*/\*)")
_DBMS_OUTPUT = re.compile(r"\bdbms_output\.", re.IGNORECASE)
_UPDATE_TRIGGERS = ("trackor updated", "trackor created/updated", "trackor created or updated")
LONG_SYNC_LINES = 250


def _strip_comments(line: str) -> str:
    return re.sub(r"--.*$", "", re.sub(r"/\*.*?\*/", "", line))


def _hint(line: int, severity: str, title: str, detail: str) -> dict[str, Any]:
    return {"line": line, "severity": severity, "title": title, "detail": detail}


def hints(code: str, node: dict[str, Any], known: set[int] | None = None) -> list[dict[str, Any]]:
    lines = code.replace("\r\n", "\n").split("\n")
    found: list[dict[str, Any]] = []
    depth = 0
    flagged_lookup = flagged_nested = False

    for number, raw in enumerate(lines, 1):
        line = _strip_comments(raw)
        starts_loop = False
        if _LOOP_END.search(line):
            depth = max(0, depth - 1)
        elif _LOOP_START.search(line):
            starts_loop = True
            depth += 1
            if depth == 2 and not flagged_nested:
                flagged_nested = True
                found.append(
                    _hint(
                        number,
                        "warn",
                        "Nested loops",
                        "A loop inside a loop runs its body rows x rows times. A single query "
                        "with a join is usually much faster.",
                    )
                )
        if depth and not starts_loop and _LOOKUP.search(line) and not flagged_lookup:
            flagged_lookup = True
            found.append(
                _hint(
                    number,
                    "warn",
                    "Query inside a loop",
                    "This runs once per row. Join the data into the loop's cursor instead of "
                    "looking it up row by row.",
                )
            )
        if _SELECT_STAR.search(line):
            found.append(
                _hint(
                    number,
                    "info",
                    "SELECT *",
                    "Name the columns you need: it reads less and does not break when columns "
                    "are added.",
                )
            )
        if _COMMIT.search(line):
            found.append(
                _hint(
                    number,
                    "error",
                    "COMMIT or ROLLBACK in a rule",
                    "Rules run inside the platform's transaction. Committing here can save "
                    "half-finished work or break the caller.",
                )
            )
        if _DYNAMIC.search(line):
            found.append(
                _hint(
                    number,
                    "warn",
                    "Dynamic SQL built from strings",
                    "Concatenated SQL is re-parsed every time and can break on quotes. Use bind "
                    "variables with EXECUTE IMMEDIATE ... USING.",
                )
            )
        if _SWALLOW.search(line):
            found.append(
                _hint(
                    number,
                    "error",
                    "Errors are silently ignored",
                    "WHEN OTHERS THEN NULL hides every failure, so problems show up later as "
                    "wrong data. Handle the specific exception or let it raise.",
                )
            )
        if _DBMS_OUTPUT.search(line):
            found.append(
                _hint(
                    number,
                    "info",
                    "DBMS_OUTPUT",
                    "Output written with DBMS_OUTPUT is not shown anywhere when a rule runs.",
                )
            )
        # Config ids are how rules name fields and types; only unknown numbers are suspicious.
        literal = next(
            (m for m in _LITERAL.finditer(line) if int(m.group(1)) not in (known or set())), None
        )
        if literal and "id." not in line.lower():
            found.append(
                _hint(
                    number,
                    "info",
                    "Hard-coded value",
                    f"{literal.group(1)} is hard-coded. If it is an id or a task number, a "
                    "lookup by name survives renumbering and copies between instances.",
                )
            )

    text = "\n".join(_strip_comments(line) for line in lines)
    if "no_data_found" not in text.lower() and "when others" not in text.lower():
        for match in _SELECT_INTO.finditer(text):
            if not _AGGREGATE.search(match.group(0)):
                line = text[: match.start()].count("\n") + 1
                found.append(
                    _hint(
                        line,
                        "warn",
                        "SELECT INTO can fail with no data",
                        "If no row matches, this raises NO_DATA_FOUND and the whole rule fails. "
                        "Use MAX(...), a cursor, or handle NO_DATA_FOUND.",
                    )
                )
                break

    if node.get("type") == "rule":
        trigger = str(node.get("trigger") or "").lower()
        if any(t in trigger for t in _UPDATE_TRIGGERS) and not node.get("filtered"):
            found.append(
                _hint(
                    1,
                    "warn",
                    "Runs on every update",
                    "This rule fires on every change to the trackor and has no filter. A filter "
                    "or a field-update trigger avoids running it when it cannot matter.",
                )
            )
        if not node.get("async") and len(lines) > LONG_SYNC_LINES:
            found.append(
                _hint(
                    1,
                    "info",
                    "Long rule runs while the user waits",
                    f"{len(lines)} lines run synchronously. If the result is not needed "
                    "immediately, making the rule async keeps saves fast.",
                )
            )

    order = {"error": 0, "warn": 1, "info": 2}
    return sorted(found, key=lambda h: (order[h["severity"]], h["line"]))
