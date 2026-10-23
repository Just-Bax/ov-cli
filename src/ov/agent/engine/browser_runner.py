from __future__ import annotations

from typing import Any

RUNNER_STEPS = 40
KEPT_SCREENSHOTS = 2
KEPT_PAGES = 2
PAGE_OUTPUT_CHARS = 2_000
RUNNER_EFFORT = "low"
STEPS_USED_UP = (
    "Result: stuck\nThe browser assistant used all {steps} steps without finishing. Look at the screen and "
    "give it a smaller goal."
)
OLD_SCREENSHOT = "[older screenshot removed]"
OLD_PAGE = "[older page snapshot removed; take a new snapshot to see the page]"
LATEST_SCREENSHOT = "Screenshot after the last action:"
NO_REPORT = "The browser assistant finished without a report."
RUNNER_PROMPT = """You are the hands of an engineer. You drive a web browser that the user watches live, to reach \
one goal the engineer gave you. Work quickly and carefully:
- Start with browser_snapshot. It lists the page as an accessibility tree; aim at elements by their ref, e.g. \
ref=e14. Use x and y only from a screenshot you asked for.
- Actions return only what they did and the URL, not the page. When the snapshot already shows the next steps, \
send them together in one browser_steps call (fill the fields, choose the status, click Save) instead of one \
tool call each, then take a snapshot to see the result.
- Ask for a screenshot (browser_snapshot with screenshot=true) only when the tree does not tell you enough, such \
as for layout, colors or charts.
- When a browser tool fails, read the error: it says what blocked it. Take a new snapshot and try a different way \
once. If that also fails, stop and report; never repeat the same action hoping for another result.
- Give every action a short say line in plain words; the user reads it over the browser.
- Do only what the goal asks. Never save, delete, run or send anything the goal does not ask for. A change that \
is blocked or rejected is final: stop there.
- To upload a file the goal names, use browser_upload on the page's upload button or file field.
- Alerts, confirms and prompts the page shows are real dialogs: answer them with browser_dialog. A page that \
opens a new window gets a new tab: the snapshot lists tabs, browser_tab switches or closes them.
- If the page itself shows something unexpected (an error message, a dialog you did not expect, a missing \
button, a read-only field), stop and report it instead of trying another way.
When you finish or stop, reply with this report and nothing else:
Result: done | stuck | failed
Steps: what you did, one short line each
Seen: what the screen showed that answers the goal (names, values, messages)
Problem: what went wrong, or none
ASCII only."""


class RunnerError(Exception):
    pass


def report(text: str | None) -> str:
    if not text or not text.strip():
        raise RunnerError(NO_REPORT)
    return text


def drop_old_pages(messages: list[dict[str, Any]]) -> None:
    shots = [m for m in messages if m["role"] == "user" and isinstance(m["content"], list)]
    for message in shots[:-KEPT_SCREENSHOTS]:
        message["content"] = OLD_SCREENSHOT
    pages = [m for m in messages if m["role"] == "tool" and len(m["content"]) > PAGE_OUTPUT_CHARS]
    for message in pages[:-KEPT_PAGES]:
        message["content"] = OLD_PAGE
