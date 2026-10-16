from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from ov.agent import skills
from ov.agent import workspace as project
from ov.agent.engine.files import IMAGE_EXTS, image_mime, within
from ov.agent.integrations import datadog, pagerduty
from ov.agent.tools.base import (
    LABEL_CHARS,
    Tool,
    ToolContext,
    ToolError,
    clip,
    int_param,
    serial,
    string_param,
    strings_param,
)
from ov.agent.tools.onevizion import entity_link

READ_FILE_LINES = 500
MAX_IMAGE_BYTES = 5 * 1024 * 1024
BINARY_SNIFF_BYTES = 4096
TEXT_COPY_SUFFIX = ".txt"
MAX_QUESTIONS = 5
MIN_OPTIONS = 2
MAX_OPTIONS = 5
HEADER_CHARS = 12

ENTITY_TYPES = (
    "rule",
    "automation",
    "workflow",
    "report",
    "import",
    "db package",
    "notification",
    "field formula",
    "module file",
    "data fix",
)


def attachment_names(ctx: ToolContext) -> list[str]:
    directory = ctx.work_dir / "attachments"
    if not directory.is_dir():
        return []
    names = {p.name for p in directory.iterdir()}
    return sorted(n for n in names if not (n.endswith(TEXT_COPY_SUFFIX) and n.removesuffix(TEXT_COPY_SUFFIX) in names))


def offered_skills() -> list[dict[str, Any]]:
    hidden = {
        name
        for name, linked in (
            ("datadog", datadog.connected),
            ("pagerduty", pagerduty.connected),
            ("workspace", project.configured),
        )
        if not linked()
    }
    return [s for s in skills.enabled_skills() if s["name"] not in hidden]


def _read_skill(args: dict[str, Any], _ctx: ToolContext) -> str:
    name = str(args["name"]).strip()
    found = next((s for s in offered_skills() if s["name"] == name), None)
    if found is None:
        names = ", ".join(s["name"] for s in offered_skills())
        raise ToolError(f"No skill named {name}. Skills: {names}.")
    return f"# {found['title']}\n\n{found['content']}"


def _locate(rel: str, ctx: ToolContext) -> Path:
    path = within(ctx.work_dir, rel)
    if not path.exists() and (ctx.work_dir / "attachments").is_dir():
        path = within(ctx.work_dir / "attachments", Path(rel).name)
    if not path.is_file():
        listed = ", ".join(attachment_names(ctx)) or "none"
        raise ToolError(f"No such file: {rel}. Attachments: {listed}")

    if path.parent.name == "attachments":
        ctx.opened.add(path.name)
    return path


def _read_image(path: Path, ctx: ToolContext) -> str:
    if not ctx.vision:
        return "This model cannot view images. Switch to a vision model to read screenshots."

    raw = path.read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ToolError(
            f"{path.name} is {len(raw) / 1024 / 1024:.1f} MB; images over {MAX_IMAGE_BYTES // 1024 // 1024} MB "
            "cannot be sent to the model. Ask the user for a smaller screenshot."
        )

    data = base64.b64encode(raw).decode("ascii")
    ctx.attach_image(path.name, f"data:{image_mime(path)};base64,{data}")
    return f"Image {path.name} is attached in the next message."


def _read_file(args: dict[str, Any], ctx: ToolContext) -> str:
    path = _locate(str(args["path"]), ctx)
    if path.suffix.lower() in IMAGE_EXTS:
        return _read_image(path, ctx)

    expanded = Path(f"{path}{TEXT_COPY_SUFFIX}")
    if path.suffix.lower() == ".eml" and expanded.exists():
        path = expanded
    raw = path.read_bytes()
    if b"\0" in raw[:BINARY_SNIFF_BYTES]:
        return f"Binary file {path.name} ({len(raw)} bytes); cannot be read as text."

    lines = raw.decode("utf-8", "replace").split("\n")
    first = max(1, int(args.get("start") or 1))
    last = min(len(lines), int(args.get("end") or first + READ_FILE_LINES - 1))
    tail = f"\n... ({len(lines)} lines)" if last < len(lines) else ""
    return clip("\n".join(lines[first - 1 : last]) + tail, ctx, "file")


def _text_arg(args: dict[str, Any], key: str, ctx: ToolContext) -> str:
    source = args.get(f"{key}_file")
    if not source:
        return str(args.get(key) or "")
    if args.get(key):
        raise ToolError(f"Pass {key} or {key}_file, not both.")
    name = str(source)
    run_file = within(ctx.work_dir, name)
    if run_file.is_file():
        return run_file.read_text(encoding="utf-8", errors="replace")
    if project.configured():
        return project.text_of(name)
    raise ToolError(f"No such file in the run folder: {name}")


def _propose_change(args: dict[str, Any], ctx: ToolContext) -> str:
    entity_type = str(args["entity_type"]).strip().lower()
    if entity_type not in ENTITY_TYPES:
        raise ToolError(f"entity_type must be one of: {', '.join(ENTITY_TYPES)}. Put details in the title or what.")
    entity_id = str(args["entity_id"]) if args.get("entity_id") else None
    instance = str(args.get("instance") or ctx.instance) or None
    change = {
        "id": f"chg_{int(time.time() * 1000)}_{serial()}",
        "title": str(args["title"]),
        "entityType": entity_type,
        "entityId": entity_id,
        "entityName": str(args["entity_name"]) if args.get("entity_name") else None,
        "instance": instance,
        "link": entity_link(entity_type, entity_id, instance) or args.get("link") or None,
        "language": "sql" if args["language"] == "plsql" else str(args["language"]),
        "before": _text_arg(args, "before", ctx),
        "after": _text_arg(args, "after", ctx),
        "what": str(args["what"]),
        "why": str(args["why"]),
        "how": str(args["how"]),
    }

    if not change["after"].strip():
        raise ToolError("Give the proposed text in after or after_file.")
    ctx.emit({"type": "change", "change": {k: v for k, v in change.items() if v is not None}})
    return f"Change card shown ({change['id']})."


def _option(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or not str(raw.get("label") or "").strip():
        raise ToolError("Every option needs a label.")
    option = {"label": str(raw["label"]).strip()}
    if str(raw.get("description") or "").strip():
        option["description"] = str(raw["description"]).strip()
    return option


def _question_item(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not str(raw.get("question") or "").strip():
        raise ToolError("Every question needs question text.")

    options = [_option(o) for o in raw.get("options") or []]
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise ToolError(f"Give {MIN_OPTIONS}-{MAX_OPTIONS} options per question; the user can also type their own.")

    return {
        "header": str(raw.get("header") or "").strip()[:HEADER_CHARS],
        "question": str(raw["question"]).strip(),
        "options": options,
        "multiple": raw.get("multiple") is True,
    }


def _ask_label(args: dict[str, Any]) -> str:
    questions = args.get("questions") or [{}]
    first = questions[0] if isinstance(questions[0], dict) else {}
    more = f" (+{len(questions) - 1})" if len(questions) > 1 else ""
    return f"ask: {str(first.get('question', ''))[:LABEL_CHARS]}{more}"


def _ask_user(args: dict[str, Any], ctx: ToolContext) -> str:
    raw = args.get("questions") or []
    if not 1 <= len(raw) <= MAX_QUESTIONS:
        raise ToolError(f"Ask 1-{MAX_QUESTIONS} questions at once.")

    items = [_question_item(q) for q in raw]
    answers = ctx.ask_user(items)
    pairs = enumerate(zip(items, answers, strict=True), 1)
    lines = [f"{i}. {item['header'] or item['question']}: {answer}" for i, (item, answer) in pairs]
    return "User answered:\n" + "\n".join(lines)


def _existing(entries: list[Any]) -> list[dict[str, str]]:
    if any(not isinstance(e, dict) or not e.get("key") for e in entries):
        raise ToolError("Every existing entry needs a key.")
    return [{k: str(e[k]) for k in ("key", "title", "covers", "note", "link") if e.get(k)} for e in entries]


def _finish(args: dict[str, Any], ctx: ToolContext) -> str:
    findings = args["findings"]
    if any(not f.get("evidence") for f in findings):
        raise ToolError(
            "Not finished: every finding needs evidence you verified yourself. Check, then call run_report again."
        )

    unread = [] if ctx.has_outcome() else [n for n in attachment_names(ctx) if n not in ctx.opened]
    if unread:
        raise ToolError(f"Not finished: open every attachment first. Unread: {', '.join(unread)}")

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
        "existing": _existing(args.get("existing") or []),
        "unrelated": [str(u) for u in args.get("unrelated") or []],
        "reply": str(args.get("reply") or ""),
    }

    ctx.finish(outcome)
    return "Delivered."


TOOLS = [
    Tool(
        "skill_read",
        "Read a skill: the full guide for an area listed under Skills in the prompt. Read every skill "
        "that covers the task before working on it.",
        {"name": string_param("Skill name, as listed under Skills")},
        ["name"],
        lambda a: f"skill {a.get('name')}",
        _read_skill,
    ),
    Tool(
        "run_read",
        "Read a file from this run's folder: attachments the user sent, files saved with "
        "ov --out, and spilled tool output. Images are shown to you; emails are expanded to text.",
        {
            "path": string_param("Path relative to the run folder, or an attachment name"),
            "start": int_param("First line, 1-based"),
            "end": int_param("Last line"),
        },
        ["path"],
        lambda a: f"read {a.get('path')}",
        _read_file,
    ),
    Tool(
        "ov_propose",
        "Show a proposed change to code or component text (rule, automation or workflow "
        "expression, report SQL, module file, PL/SQL data fix) as a diff card. One call per "
        "object. Nothing is applied. Pass the whole object text in both before and after, any length; "
        "for long code write it to a file and pass after_file. Never "
        "use it for record deletes, value edits, cleanup or UI steps; say those in chat.",
        {
            "title": string_param("Short title of the fix, at most 8 words"),
            "entity_type": {"type": "string", "enum": list(ENTITY_TYPES), "description": "Kind of object changed"},
            "entity_id": string_param("ID if known"),
            "entity_name": string_param("Name as shown in the admin UI"),
            "instance": string_param("Instance host"),
            "link": string_param(
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
            "before": string_param(
                "The COMPLETE current text exactly as fetched, never a fragment. Empty only "
                "for new objects or PL/SQL data fixes."
            ),
            "after": string_param("The COMPLETE proposed code, same scope as before; never prose"),
            "before_file": string_param(
                "Instead of before: a file with the current text, in the run folder or workspace"
            ),
            "after_file": string_param(
                "Instead of after: a file with the proposed text, in the run folder or workspace"
            ),
            "what": string_param("What changes, one sentence"),
            "why": string_param("Why, one sentence"),
            "how": string_param("How to apply it, one sentence"),
        },
        ["title", "entity_type", "language", "what", "why", "how"],
        lambda a: f"propose {a.get('entity_type')}: {a.get('title')}",
        _propose_change,
        silent=True,
    ),
    Tool(
        "run_ask",
        "Ask the user before working when an input you need is missing or ambiguous: which instance, which "
        "object, the scope, or the outcome wanted. Put related questions in one call; they are answered "
        "together. Do not ask about facts you can look up. Blocks until answered.",
        {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_QUESTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "header": string_param(f"Topic chip, at most {HEADER_CHARS} chars, e.g. Instance"),
                        "question": string_param("One short question"),
                        "options": {
                            "type": "array",
                            "minItems": MIN_OPTIONS,
                            "maxItems": MAX_OPTIONS,
                            "description": "Distinct choices; the user can also type their own",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": string_param("The choice, 1-5 words"),
                                    "description": string_param("What picking it means, one short line"),
                                },
                                "required": ["label"],
                                "additionalProperties": False,
                            },
                        },
                        "multiple": {"type": "boolean", "description": "Allow picking several options"},
                    },
                    "required": ["header", "question", "options"],
                    "additionalProperties": False,
                },
            },
        },
        ["questions"],
        _ask_label,
        _ask_user,
        silent=True,
    ),
    Tool(
        "run_report",
        "Deliver a structured report: only when working a support case, or when the user asks for a "
        "report of findings. Everything else is answered in chat. The user may ask follow-ups afterwards.",
        {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": string_param("The finding in a few words"),
                        "verdict": {
                            "type": "string",
                            "enum": ["fix", "fixed", "user_action", "expected", "info", "unknown"],
                            "description": "fix = a change is still needed; fixed = already "
                            "resolved and verified; user_action = someone must act; expected = "
                            "works as designed; info = an answer or fact",
                        },
                        "summary": string_param("Short answer to what was asked, plain language"),
                        "still_happening": {"type": "boolean"},
                        "evidence": strings_param(
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
                        "key": string_param("Issue or task key"),
                        "title": string_param("Summary"),
                        "covers": {"type": "string", "enum": ["yes", "partly", "no"]},
                        "note": string_param("One short sentence"),
                        "link": string_param("URL"),
                    },
                    "required": ["key", "title", "covers"],
                    "additionalProperties": False,
                },
            },
            "unrelated": strings_param("Unrelated problems noticed, one sentence each"),
            "reply": string_param(
                "Only when working a case: the case chat comment in the reply style - short paragraphs "
                "separated by blank lines: update, what the problem was, what I did, current status and "
                "next step. Or when the user asks for a message to send. Otherwise leave it out."
            ),
        },
        ["findings"],
        lambda _: "report",
        _finish,
        silent=True,
    ),
]
