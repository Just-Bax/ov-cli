from __future__ import annotations

import base64
import itertools
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from ..errors import EXIT_READ_ONLY
from . import sources
from .cancel import Cancel
from .ovproc import OvResult, find_instance, host_of, run_ov
from .workspace import IMAGE_EXTS, image_mime, within

MAX_OUTPUT = 24_000
OV_TIMEOUT_SECONDS = 180
MAX_TIME_SAVED_MINUTES = 8 * 60

BLOCKED_COMMANDS = {"login", "logout", "use", "config", "setup", "spec", "tenants", "agent", "ui"}

# Edit forms of the platform's admin grids, keyed by what the model calls the object.
EDIT_FORMS = (
    (re.compile(r"rule", re.IGNORECASE), "/admin/rules/Form.do?id="),
    (re.compile(r"report", re.IGNORECASE), "/admin/reports/Form.do?id="),
    (re.compile(r"automation", re.IGNORECASE), "/admin/automation/Form.do?id="),
    (re.compile(r"trackor|record", re.IGNORECASE), "/form/ConfigAppForm.do?id="),
)

_counter = itertools.count(1)


class ToolError(Exception):
    pass


class ToolContext(Protocol):
    work_dir: Path
    cancel: Cancel
    vision: bool
    instance: str
    opened: set[str]

    def emit(self, event: dict[str, Any]) -> None: ...
    def has_outcome(self) -> bool: ...
    def ask_user(
        self, question: str, options: list[str], multiple: bool, detail: str | None = None
    ) -> str: ...
    def require_login(self, host: str) -> bool: ...
    def attach_image(self, name: str, url: str) -> None: ...
    def finish(self, outcome: dict[str, Any]) -> None: ...
    def can_write(self) -> bool: ...
    def load_case(self, ref: str) -> str: ...


Handler = Callable[[dict[str, Any], ToolContext], str]


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    label: Callable[[dict[str, Any]], str]
    handler: Handler
    silent: bool = False

    @property
    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
                    "required": self.required,
                    "additionalProperties": False,
                },
            },
        }


def _str(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _int(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


def _strings(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def entity_link(entity_type: str, entity_id: str | None, instance: str | None) -> str | None:
    if not entity_id or not instance or not entity_id.strip().isdigit():
        return None
    form = next((path for pattern, path in EDIT_FORMS if pattern.search(entity_type)), None)
    return f"https://{host_of(instance)}{form}{entity_id.strip()}" if form else None


# Over budget, the rest is spilled to a workspace file the model can page through.
def clip(text: str, ctx: ToolContext, what: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    name = f"output-{int(time.time() * 1000)}-{next(_counter)}.txt"
    (ctx.work_dir / name).write_text(text, encoding="utf-8")
    return (
        f"{text[:MAX_OUTPUT]}\n\n[truncated: {len(text)} chars total. Full {what} saved as "
        f'"{name}"; read more with read_file]'
    )


def _output(result: OvResult) -> str:
    stderr = result.stderr.strip()
    body = "\n".join(p for p in (result.stdout.strip(), stderr and f"[stderr] {stderr}") if p)
    if result.code != 0:
        raise ToolError(body or f"ov exited with code {result.code}")
    return body or "(empty response)"


def _target(instance: str | None, ctx: ToolContext) -> str:
    target = (instance or ctx.instance or "").strip()
    if not target:
        raise ToolError("No instance given. Pass instance, or ask the user which one.")
    return target


def _alias_for(target: str, ctx: ToolContext) -> tuple[str, str]:
    found = find_instance(target)
    if found is None:
        if not ctx.require_login(host_of(target)):
            raise ToolError(f"Not signed in to {target} and the user skipped sign-in.")
        found = find_instance(target)
        if found is None:
            raise ToolError(f"Still no signed-in instance for {target}.")
    return found["alias"], found["host"]


def _quoted(args: list[str]) -> str:
    return " ".join(json.dumps(a) if re.search(r"[\s\"']", a) else a for a in args)


def _confine(path: str, ctx: ToolContext) -> str:
    return str(within(ctx.work_dir, Path(path).name))


# Keeps every file ov reads or writes inside the run's workspace.
def _confine_files(args: list[str], ctx: ToolContext) -> list[str]:
    out: list[str] = []
    expect = ""
    for arg in args:
        if expect:
            if expect == "--out":
                arg = _confine(arg, ctx)
            elif expect == "--file":
                field, _, path = arg.partition("=")
                arg = f"{field}=@{_confine(path.strip().lstrip('@'), ctx)}"
            elif arg.startswith("@"):
                arg = "@" + _confine(arg[1:], ctx)
            out.append(arg)
            expect = ""
            continue

        flag, sep, value = arg.partition("=")
        if flag in ("--out", "--file", "-d", "--data") and not sep:
            expect = "--data" if flag == "-d" else flag
            out.append(arg)
        elif sep and flag in ("--out", "--file", "--data"):
            out.extend(_confine_files([flag, value], ctx))
        elif arg.startswith("-d") and len(arg) > 2 and not arg.startswith("--"):
            out.extend(_confine_files(["-d", arg[2:].removeprefix("=")], ctx))
        else:
            out.append(arg)
    return out


_SQL_ROUTE = re.compile(r"^/?(api/)?v\d+/sql/", re.IGNORECASE)


def run_ov_tool(
    args: list[str], instance: str | None, ctx: ToolContext, allow_sql: bool = False
) -> str:
    cleaned = [str(a) for a in args]
    if cleaned[:1] == ["ov"]:
        cleaned.pop(0)
    if not cleaned:
        raise ToolError("No ov arguments given.")
    if cleaned[0].startswith("-"):
        raise ToolError('Start with the command, e.g. ["request", "GET", "/v3/..."].')
    if cleaned[0] in BLOCKED_COMMANDS:
        raise ToolError(f'"{cleaned[0]}" is not allowed from the agent.')
    if any(a.startswith("--instance") or (a.startswith("-i") and a[:2] != "--") for a in cleaned):
        raise ToolError("Pass the instance in the instance parameter, not as -i.")
    if not allow_sql and (cleaned[0] == "sql" or any(_SQL_ROUTE.search(a) for a in cleaned)):
        raise ToolError("Run SQL with the sql tool, not through ov.")
    cleaned = _confine_files(cleaned, ctx)

    target = _target(instance, ctx)
    for attempt in range(2):
        alias, host = _alias_for(target, ctx)
        result = run_ov(
            ["-i", alias, *cleaned],
            timeout=OV_TIMEOUT_SECONDS,
            cancel=ctx.cancel,
            cwd=ctx.work_dir,
        )
        if result.is_auth and attempt == 0:
            if not ctx.require_login(host):
                raise ToolError(f"Session for {target} expired and the user skipped sign-in.")
            continue
        if result.timed_out:
            raise ToolError(f"ov timed out after {OV_TIMEOUT_SECONDS}s")
        if result.code == EXIT_READ_ONLY:
            return _write(alias, host, cleaned, ctx)
        return clip(_output(result), ctx, "ov output")
    raise ToolError(f"Still not signed in to {target}.")


def _write(alias: str, host: str, args: list[str], ctx: ToolContext) -> str:
    blocked = ToolError(
        "Blocked: this would change data and write access is OFF for this run. Do not "
        "retry. Show the change with propose_change and tell the user they can turn on "
        '"Allow changes" below the chat if they want you to apply it.'
    )
    if not ctx.can_write():
        raise blocked
    command = f"ov -i {host} {_quoted(args)}"
    answer = ctx.ask_user(f"Apply this change on {host}?", ["Approve", "Reject"], False, command)
    if answer != "Approve":
        raise ToolError("The user rejected this change. Do not retry it.")
    # Write access may have been switched off while the approval was pending.
    if not ctx.can_write():
        raise blocked

    result = run_ov(
        ["-i", alias, *args],
        timeout=OV_TIMEOUT_SECONDS,
        read_only=False,
        cancel=ctx.cancel,
        cwd=ctx.work_dir,
    )
    if result.timed_out:
        raise ToolError(f"ov timed out after {OV_TIMEOUT_SECONDS}s")
    return clip(f"Applied.\n{_output(result)}", ctx, "ov output")


def _format_sql(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(parsed, dict):
        return raw
    if parsed.get("status") != "SUCCESS":
        return f"SQL failed: {parsed.get('error_message') or raw}"

    def cell(value: Any) -> str:
        if value is None:
            return "NULL"
        return str(value).replace("\t", " ").replace("\r\n", "\\n").replace("\n", "\\n")

    lines = ["\t".join(parsed.get("columns") or [])]
    lines += ["\t".join(cell(c) for c in row.get("cells", [])) for row in parsed.get("rows") or []]
    shown = parsed.get("response_rows") or 0
    total = parsed.get("total_rows") or 0
    more = f", {total} total" if total > shown else ""
    return f"{shown} rows{more} (tab separated)\n" + "\n".join(lines)


_SELECT = re.compile(r"^(select|with)\b", re.IGNORECASE)
# Oracle lets WITH declare a PL/SQL function, which can run DML.
_PLSQL_IN_WITH = re.compile(r"\bwith\s+(function|procedure)\b", re.IGNORECASE)
# Keeps stored credentials out of the model's context.
_SECRET_SQL = re.compile(
    r"password|passwd|secret|\bselect\s+\*\s+from\s+(module|users?|auth_token\w*)\b", re.IGNORECASE
)


def _sql(args: dict[str, Any], ctx: ToolContext) -> str:
    query = re.sub(r";\s*$", "", str(args["query"]).strip())
    if not _SELECT.match(query) or _PLSQL_IN_WITH.search(query):
        raise ToolError("Only SELECT / WITH queries are allowed.")
    if _SECRET_SQL.search(query):
        raise ToolError("Do not read credential columns. Select the non-secret columns you need.")

    rows = min(max(int(args.get("rows") or 100), 1), 1000)
    raw = run_ov_tool(
        [
            "sql",
            "check-sql-and-return-result-set",
            "-q",
            f"rows_count={rows}",
            "-d",
            query,
            "--json",
        ],
        args.get("instance"),
        ctx,
        allow_sql=True,
    )
    return clip(_format_sql(raw), ctx, "result")


def _trackor_search(args: dict[str, Any], ctx: ToolContext) -> str:
    trackor_type = quote(str(args["trackor_type"]), safe="")
    limit = min(int(args.get("limit") or 50), 500)
    return run_ov_tool(
        [
            "request",
            "POST",
            f"/v3/trackor_types/{trackor_type}/trackors/search",
            "-q",
            f"fields={','.join(args['fields'])}",
            "-q",
            "page=1",
            "-q",
            f"per_page={limit}",
            "-H",
            "Content-Type:text/plain",
            "-d",
            str(args["condition"]),
            "--json",
        ],
        args.get("instance"),
        ctx,
    )


def attachment_names(ctx: ToolContext) -> list[str]:
    directory = ctx.work_dir / "attachments"
    if not directory.is_dir():
        return []
    names = {p.name for p in directory.iterdir()}
    return sorted(n for n in names if not (n.endswith(".txt") and n[:-4] in names))


def _read_file(args: dict[str, Any], ctx: ToolContext) -> str:
    rel = str(args["path"])
    path = within(ctx.work_dir, rel)
    if not path.exists() and (ctx.work_dir / "attachments").is_dir():
        path = within(ctx.work_dir / "attachments", Path(rel).name)
    if not path.is_file():
        listed = ", ".join(attachment_names(ctx)) or "none"
        raise ToolError(f"No such file: {rel}. Attachments: {listed}")
    if path.parent.name == "attachments":
        ctx.opened.add(path.name)

    if path.suffix.lower() in IMAGE_EXTS:
        if not ctx.vision:
            return "This model cannot view images. Switch to a vision model to read screenshots."
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        ctx.attach_image(path.name, f"data:{image_mime(path)};base64,{data}")
        return f"Image {path.name} is attached in the next message."

    expanded = Path(f"{path}.txt")
    if path.suffix.lower() == ".eml" and expanded.exists():
        path = expanded
    raw = path.read_bytes()
    if b"\0" in raw[:4096]:
        return f"Binary file {path.name} ({len(raw)} bytes); cannot be read as text."

    lines = raw.decode("utf-8", "replace").split("\n")
    first = max(1, int(args.get("start") or 1))
    last = min(len(lines), int(args.get("end") or first + 499))
    tail = f"\n... ({len(lines)} lines)" if last < len(lines) else ""
    return clip("\n".join(lines[first - 1 : last]) + tail, ctx, "file")


def _source_search(args: dict[str, Any], ctx: ToolContext) -> str:
    found = sources.search(
        str(args["source"]),
        str(args["pattern"]),
        str(args.get("path") or ""),
        bool(args.get("ignore_case")),
    )
    return clip(found, ctx, "search")


def _source_read(args: dict[str, Any], ctx: ToolContext) -> str:
    end = int(args["end"]) if args.get("end") else None
    text = sources.read(str(args["source"]), str(args["path"]), int(args.get("start") or 1), end)
    return clip(text, ctx, "file")


def _git_clone(args: dict[str, Any], _: ToolContext) -> str:
    cloned = sources.clone_repo(str(args["url"]))
    return f'Use source="{cloned["repo"]}".\nFiles:\n' + "\n".join(cloned["files"])


def _propose_change(args: dict[str, Any], ctx: ToolContext) -> str:
    entity_type = str(args["entity_type"])
    entity_id = str(args["entity_id"]) if args.get("entity_id") else None
    instance = str(args.get("instance") or ctx.instance or "") or None
    change = {
        "id": f"chg_{int(time.time() * 1000)}_{next(_counter)}",
        "title": str(args["title"]),
        "entityType": entity_type,
        "entityId": entity_id,
        "entityName": str(args["entity_name"]) if args.get("entity_name") else None,
        "instance": instance,
        "link": entity_link(entity_type, entity_id, instance) or args.get("link") or None,
        "language": "sql" if args.get("language") == "plsql" else str(args["language"]),
        "before": str(args.get("before") or ""),
        "after": str(args["after"]),
        "what": str(args["what"]),
        "why": str(args["why"]),
        "how": str(args["how"]),
    }
    ctx.emit({"type": "change", "change": {k: v for k, v in change.items() if v is not None}})
    return f"Change card shown ({change['id']})."


def _ask_user(args: dict[str, Any], ctx: ToolContext) -> str:
    options = [str(o) for o in args.get("options") or []]
    return (
        f"User answered: {ctx.ask_user(str(args['question']), options, bool(args.get('multiple')))}"
    )


def _finish(args: dict[str, Any], ctx: ToolContext) -> str:
    findings = args.get("findings") or []
    if any(not f.get("evidence") for f in findings):
        raise ToolError(
            "Not finished: every finding needs evidence you verified yourself. Check, then call "
            "finish again."
        )
    unread = [] if ctx.has_outcome() else [n for n in attachment_names(ctx) if n not in ctx.opened]
    if unread:
        raise ToolError(f"Not finished: open every attachment first. Unread: {', '.join(unread)}")

    minutes = round(float(args.get("time_saved_minutes") or 0))
    outcome = {
        "issues": [
            {
                "title": str(f["title"]),
                "verdict": str(f["verdict"]),
                "summary": str(f["summary"]),
                "stillHappening": f.get("still_happening"),
                "evidence": [str(e) for e in f["evidence"]],
            }
            for f in findings
        ],
        "existing": [
            {k: str(e[k]) for k in ("key", "title", "covers", "note", "link") if e.get(k)}
            for e in args.get("existing") or []
            if isinstance(e, dict) and e.get("key")
        ],
        "unrelated": [str(u) for u in args.get("unrelated") or []],
        "reply": str(args.get("reply") or ""),
        "timeSaved": {
            "minutes": min(MAX_TIME_SAVED_MINUTES, max(0, minutes)),
            "basis": str(args.get("time_saved_basis") or ""),
        },
    }
    ctx.finish(outcome)
    return "Delivered."


def _ov_label(a: dict[str, Any]) -> str:
    at = f" @ {a['instance']}" if a.get("instance") else ""
    return f"ov {' '.join(str(x) for x in (a.get('args') or [])[:4])}{at}"


INSTANCE = _str("Instance alias or host. Defaults to the run's instance, if one is set.")

TOOLS = [
    Tool(
        "load_case",
        "Read a support case from trackor.onevizion.com: every field, the full chat, and all "
        "attachments (saved to the workspace; open each with read_file). Also sets the run's "
        "instance to the case's affected instance (C_WEBSITE).",
        {"case": _str("Case number (e.g. 193915) or a trackor.onevizion.com case link")},
        ["case"],
        lambda a: f"Read case {a.get('case')} from trackor",
        lambda a, ctx: ctx.load_case(str(a.get("case", ""))),
    ),
    Tool(
        "ov",
        "Run the ov CLI against a OneVizion instance: any API call, schema discovery (api list, "
        "api show), component export, chats, files. Reads always work. Calls that change data "
        "are blocked unless the user allowed changes for this run, and then each one waits for "
        "the user to approve it.",
        {
            "instance": INSTANCE,
            "args": _strings(
                'Arguments after "ov -i <alias>", e.g. ["request","GET","/v3/trackors/123",'
                '"-q","fields=A,B"]'
            ),
        },
        ["args"],
        _ov_label,
        lambda a, ctx: run_ov_tool(list(a.get("args") or []), a.get("instance"), ctx),
    ),
    Tool(
        "sql",
        "Run a read-only SELECT (or WITH) on an instance database through the platform's Test "
        "SQL endpoint. Max 1000 rows.",
        {
            "instance": INSTANCE,
            "query": _str("A single SELECT statement, no trailing semicolon"),
            "rows": _int("Row limit, default 100, max 1000"),
        },
        ["query"],
        lambda a: (
            f"SQL{' @ ' + a['instance'] if a.get('instance') else ''}: "
            + re.sub(r"\s+", " ", str(a.get("query", "")))[:80]
        ),
        _sql,
    ),
    Tool(
        "trackor_search",
        "Search trackors of a type with a condition (equal, not_equal, greater, less, within, "
        "is_null, is_not_null, and/or, parentheses). String and date values in double quotes.",
        {
            "instance": INSTANCE,
            "trackor_type": _str("Trackor type name"),
            "fields": _strings("Field names to return"),
            "condition": _str('e.g. equal(TRACKOR_KEY, "P-100") and greater(F_DATE, "2026-01-01")'),
            "limit": _int("Max rows, default 50"),
        },
        ["trackor_type", "fields", "condition"],
        lambda a: f"search {a.get('trackor_type')}: {str(a.get('condition', ''))[:70]}",
        _trackor_search,
    ),
    Tool(
        "read_file",
        "Read a file from this run's workspace: attachments the user sent, files saved with "
        "ov --out, and spilled tool output. Images are shown to you; emails are expanded to text.",
        {
            "path": _str("Path relative to the workspace, or an attachment name"),
            "start": _int("First line, 1-based"),
            "end": _int("Last line"),
        },
        ["path"],
        lambda a: f"read {a.get('path')}",
        _read_file,
    ),
    Tool(
        "source_search",
        "git grep (extended regex) in a configured source (code or docs folder) or a cloned "
        'repo ("repo:<name>").',
        {
            "source": _str('Source name, or "repo:<name>" for a repo from git_clone'),
            "pattern": _str("Extended regex"),
            "path": _str('Optional pathspec, e.g. "db/*" or "*.py"'),
            "ignore_case": {"type": "boolean"},
        },
        ["source", "pattern"],
        lambda a: f"grep {a.get('source')}: {a.get('pattern')}",
        _source_search,
    ),
    Tool(
        "source_read",
        "Read a file, or list a directory, from a source or cloned repo.",
        {
            "source": _str('Source name or "repo:<name>"'),
            "path": _str("Path inside the source; empty string for its root"),
            "start": _int("First line"),
            "end": _int("Last line"),
        },
        ["source", "path"],
        lambda a: f"read {a.get('source')}/{a.get('path')}",
        _source_read,
    ),
    Tool(
        "git_clone",
        "Clone or update a git repository (e.g. a Vizion Hub module from MODULE.GIT_REPO_URL) "
        "so it can be searched with source_search. Returns its file list.",
        {"url": _str("Repository URL")},
        ["url"],
        lambda a: f"clone {str(a.get('url', '')).rstrip('/').rsplit('/', 1)[-1]}",
        _git_clone,
    ),
    Tool(
        "propose_change",
        "Show a proposed change as a diff card. One call per object. Nothing is applied. Pass "
        "the whole object text in both before and after.",
        {
            "title": _str("Short title"),
            "entity_type": _str("rule, report, automation, module file, data fix, field, ..."),
            "entity_id": _str("ID if known"),
            "entity_name": _str("Name as shown in the admin UI"),
            "instance": _str("Instance host"),
            "link": _str(
                "Direct URL to the object, only for types without a known edit form (rules, "
                "reports, automations and trackors get one automatically from entity_id)"
            ),
            "language": {
                "type": "string",
                "enum": [
                    "sql",
                    "plsql",
                    "python",
                    "javascript",
                    "typescript",
                    "json",
                    "xml",
                    "html",
                    "text",
                ],
            },
            "before": _str(
                "The COMPLETE current text exactly as fetched, never a fragment. Empty only "
                "for new objects or data fixes."
            ),
            "after": _str("The COMPLETE proposed text, same scope as before"),
            "what": _str("What changes, one sentence"),
            "why": _str("Why, one sentence"),
            "how": _str("How to apply it, one sentence"),
        },
        ["title", "entity_type", "language", "after", "what", "why", "how"],
        lambda a: f"propose {a.get('entity_type')}: {a.get('title')}",
        _propose_change,
        silent=True,
    ),
    Tool(
        "ask_user",
        "Ask the user a multiple-choice question when you truly cannot proceed (which "
        "instance, which of several objects, missing access). Blocks until answered.",
        {
            "question": _str("One short question"),
            "options": _strings("2-5 short options; the user can also type their own"),
            "multiple": {"type": "boolean"},
        },
        ["question", "options"],
        lambda a: f"ask: {str(a.get('question', ''))[:60]}",
        _ask_user,
        silent=True,
    ),
    Tool(
        "finish",
        "Deliver the result of an investigation. Call once at the end; skip it for quick "
        "questions answered in chat. The user may ask follow-ups afterwards.",
        {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": _str("The finding in a few words"),
                        "verdict": {
                            "type": "string",
                            "enum": ["fix", "fixed", "user_action", "expected", "info", "unknown"],
                            "description": "fix = a change is still needed; fixed = already "
                            "resolved and verified; user_action = someone must act; expected = "
                            "works as designed; info = an answer or fact",
                        },
                        "summary": _str("Short answer to what was asked, plain language"),
                        "still_happening": {"type": "boolean"},
                        "evidence": _strings(
                            "1-4 short facts you verified yourself on the instance, e.g. "
                            '"Rule 100024528 is_enabled = 0 (checked 10/01)"'
                        ),
                    },
                    "required": ["title", "verdict", "summary", "evidence"],
                    "additionalProperties": False,
                },
            },
            "existing": {
                "type": "array",
                "description": "Closest existing Issues / Issue Tasks found on trackor",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": _str("Issue or task key"),
                        "title": _str("Summary"),
                        "covers": {"type": "string", "enum": ["yes", "partly", "no"]},
                        "note": _str("One short sentence"),
                        "link": _str("URL"),
                    },
                    "required": ["key", "title", "covers"],
                    "additionalProperties": False,
                },
            },
            "unrelated": _strings("Unrelated problems noticed, one sentence each"),
            "reply": _str(
                "Working a case: the case chat comment in the reply style - short paragraphs "
                "separated by blank lines: update, what the problem was, what I did, current "
                "status and next step. Otherwise a short message the user can forward, or empty."
            ),
            "time_saved_minutes": _int(
                "Realistic minutes an experienced TCE would have spent doing this exact "
                "investigation and write-up by hand (opening each system, writing the queries, "
                "reading the code, dead ends, writing the fix and reply), minus about 10 minutes "
                "to review your result. Base it on what the work actually needed, not on how "
                "many tool calls you made. Do not inflate."
            ),
            "time_saved_basis": _str(
                'One short sentence: what made it take that long by hand, e.g. "Tracing the '
                'rule through 3 packages and comparing 2 weeks of run logs."'
            ),
        },
        ["findings", "time_saved_minutes", "time_saved_basis"],
        lambda _: "finish",
        _finish,
        silent=True,
    ),
]

TOOL_SPECS = [t.spec for t in TOOLS]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
