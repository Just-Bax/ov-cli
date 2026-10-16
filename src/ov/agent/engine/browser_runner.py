from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import ClaudeSDKClient, ResultMessage, create_sdk_mcp_server, tool

from ov.agent.engine.cancel import Cancel
from ov.agent.engine.claude_loop import tool_handler
from ov.agent.integrations import claude, copilot
from ov.agent.storage.models import Provider
from ov.agent.tools.browser import HANDS

if TYPE_CHECKING:
    from ov.agent.engine.run import Run

RUNNER_STEPS = 40
KEPT_SCREENSHOTS = 2
RUNNER_EFFORT = "low"
MAX_TURNS_SUBTYPE = "error_max_turns"
STEPS_USED_UP = (
    "Result: stuck\nThe browser assistant used all {steps} steps without finishing. Look at the screen and "
    "give it a smaller goal."
)
OLD_SCREENSHOT = "[older screenshot removed]"
LATEST_SCREENSHOT = "Screenshot after the last action:"
INITIATOR = "agent"
NO_REPORT = "The browser assistant finished without a report."
RUNNER_PROMPT = """You are the hands of a OneVizion support engineer. You drive a web browser that the user \
watches live, to reach one goal the engineer gave you. Work like a careful person at the screen:
- Start with browser_snapshot unless the goal already shows you the screen.
- After every action look at the screenshot it returns and check it did what you expected before the next step.
- Aim by element number when the element is listed, otherwise by x and y in the latest screenshot.
- Give every action a short say line in plain words; the user reads it over the browser.
- Do only what the goal asks. Never save, delete, run or send anything the goal does not ask for. A change that \
is blocked or rejected is final: stop there.
- Alerts, confirms and prompts the page shows are real dialogs: answer them with browser_dialog. A page that \
opens a new window gets a new tab: the snapshot lists tabs, browser_tab switches or closes them.
- If something unexpected happens (an error message, a dialog you did not expect, a missing button, a read-only \
field), stop and report it instead of trying another way.
When you finish or stop, reply with this report and nothing else:
Result: done | stuck | failed
Steps: what you did, one short line each
Seen: what the screen showed that answers the goal (names, values, messages)
Problem: what went wrong, or none
ASCII only."""


def drive(run: Run, model: str, goal: str, cancel: Cancel) -> str:
    if run.provider == Provider.CLAUDE:
        return asyncio.run(_claude_drive(run, model, _claude_options(run, model), goal, cancel))
    return _copilot_drive(run, model, goal, cancel)


def _claude_server(run: Run) -> Any:
    tools = [tool(t.name, t.description, t.spec["function"]["parameters"])(tool_handler(run, t.name)) for t in HANDS]
    return create_sdk_mcp_server(claude.SERVER_NAME, tools=tools)


def _claude_options(run: Run, model: str) -> Any:
    options = claude.base_options(model, RUNNER_PROMPT, run.work_dir, claude.effort_for(model, RUNNER_EFFORT))
    options.mcp_servers = {claude.SERVER_NAME: _claude_server(run)}
    options.allowed_tools = [f"{claude.TOOL_PREFIX}*"]
    options.max_turns = RUNNER_STEPS
    options.extra_args = dict(claude.NO_TRANSCRIPT)
    return options


async def _claude_drive(run: Run, model: str, options: Any, goal: str, cancel: Cancel) -> str:
    result: ResultMessage | None = None
    loop = asyncio.get_running_loop()
    async with ClaudeSDKClient(options) as client:

        def interrupt() -> None:
            asyncio.run_coroutine_threadsafe(client.interrupt(), loop)

        with cancel.hook(interrupt):
            await client.query(goal)
            async for message in client.receive_response():
                if isinstance(message, ResultMessage):
                    result = message

    cancel.check()
    if result is None:
        raise claude.ClaudeError(NO_REPORT)

    run.record_step_usage(model, claude.usage_of(result, 0))
    if result.subtype == MAX_TURNS_SUBTYPE:
        return STEPS_USED_UP.format(steps=RUNNER_STEPS)
    if result.is_error:
        raise claude.ClaudeError(claude.result_error(result))
    return _report(result.result)


def _report(text: str | None) -> str:
    if not text or not text.strip():
        raise claude.ClaudeError(NO_REPORT)
    return text


def _ignore(_: str) -> None:
    return None


def _drop_old_screenshots(messages: list[dict[str, Any]]) -> None:
    shots = [m for m in messages if m["role"] == "user" and isinstance(m["content"], list)]
    for message in shots[:-KEPT_SCREENSHOTS]:
        message["content"] = OLD_SCREENSHOT


def _copilot_drive(run: Run, model: str, goal: str, cancel: Cancel) -> str:
    specs = [t.spec for t in HANDS]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": RUNNER_PROMPT},
        {"role": "user", "content": goal},
    ]
    for _ in range(RUNNER_STEPS):
        cancel.check()
        _drop_old_screenshots(messages)
        result = copilot.stream_chat(model, messages, specs, INITIATOR, cancel=cancel, on_text=_ignore)
        run.record_step_usage(model, result.usage)
        reply: dict[str, Any] = {"role": "assistant", "content": result.text or None}
        if result.tool_calls:
            reply["tool_calls"] = result.tool_calls
        messages.append(reply)
        if not result.tool_calls:
            return _report(result.text)

        images: list[tuple[str, str]] = []
        for call in result.tool_calls:
            args = json.loads(call["function"]["arguments"] or "{}")
            output, shots = run.call_tool_named(call["function"]["name"], args)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
            images += shots

        if images:
            parts: list[dict[str, Any]] = [{"type": "text", "text": LATEST_SCREENSHOT}]
            parts += [{"type": "image_url", "image_url": {"url": url}} for _, url in images[-1:]]
            messages.append({"role": "user", "content": parts})

    return STEPS_USED_UP.format(steps=RUNNER_STEPS)
