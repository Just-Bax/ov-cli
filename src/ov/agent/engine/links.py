from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

MIN_ID_DIGITS = 3

FORMS: tuple[tuple[str, str], ...] = (
    (r"rule\s+type", "/admin/ruletypes/Form.do?id="),
    (r"rule\s+run", "/admin/rulerun/Form.do?id="),
    (r"rule", "/admin/rules/Form.do?id="),
    (r"automation\s+run", "/admin/automationrun/Form.do?id="),
    (r"automation", "/admin/automation/Form.do?id="),
    (r"notification", "/admin/notifications/Form.do?id="),
    (r"import", "/admin/configimport/Form.do?id="),
    (r"report", "/admin/reports/Form.do?id="),
    (r"module\s+run", "/admin/modulerun/Form.do?id="),
    (r"module", "/admin/module/Form.do?id="),
    (r"process", "/admin/processes/FormErrorLog.do?id="),
    (r"trackor\s+type", "/admin/trackortypes/Form.do?id="),
    (r"(?:db\s+)?package", "/admin/dbpackage/Form.do?id="),
    (r"trackor|record", "/form/ConfigAppForm.do?id="),
)

_MENTION = re.compile(
    r"(?<![\w\[/=])(" + "|".join(f"(?:{word})" for word, _ in FORMS) + rf")\s+(?:id\s+)?#?(\d{{{MIN_ID_DIGITS},}})\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(rf"\d{{{MIN_ID_DIGITS},}}")
_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
_INSTANCE_ARG = re.compile(r'"instance"\s*:\s*"([^"]+)"')


def _tool_instance(tool: dict[str, Any]) -> str | None:
    found = _INSTANCE_ARG.search(str(tool.get("input") or ""))
    return found.group(1) if found else None


def seen_ids(state: dict[str, Any], instance: str) -> dict[str, str]:
    tools = {t["id"]: t for t in state["tools"]}
    users = {m["id"]: m for m in state["chat"] if m["role"] == "user"}
    current = instance
    seen: dict[str, str] = {}

    for item in state["items"]:
        if item["kind"] == "tool" and item["id"] in tools:
            tool = tools[item["id"]]
            current = _tool_instance(tool) or current
            text = f"{tool.get('input') or ''} {tool.get('output') or ''} {tool.get('label') or ''}"
        elif item["kind"] == "user" and item["id"] in users:
            text = users[item["id"]]["text"]
        else:
            continue
        seen.update(dict.fromkeys(_NUMBER.findall(text), current))
    return seen


def _form_for(word: str) -> str:
    normalized = " ".join(word.lower().split())
    return next(path for pattern, path in FORMS if re.fullmatch(pattern, normalized))


def links_for(text: str, seen: dict[str, str], base_urls: dict[str, str]) -> dict[str, Any]:
    hosts = {urlsplit(url).netloc.lower(): ref for ref, url in base_urls.items()}
    prose = _CODE.sub(" ", text)
    mentions = []
    for match in _MENTION.finditer(prose):
        word, number = match.group(1), match.group(2)
        base_url = base_urls.get(seen.get(number, ""))
        if base_url:
            mentions.append({"text": match.group(0), "url": f"{base_url}{_form_for(word)}{number}"})

    unverified = []
    for url in _LINK.findall(prose):
        parts = urlsplit(url)
        ids = parse_qs(parts.query).get("id") or []
        if parts.netloc.lower() in hosts and ids and ids[0] not in seen:
            unverified.append(url)
    return {"mentions": mentions, "unverified": unverified}
