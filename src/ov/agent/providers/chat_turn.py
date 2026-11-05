from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Protocol

from ov.agent.engine import compaction
from ov.agent.engine.browser_runner import (
    LATEST_SCREENSHOT,
    RUNNER_PROMPT,
    RUNNER_STEPS,
    STEPS_USED_UP,
    drop_old_pages,
    report,
)
from ov.agent.engine.cancel import Cancel
from ov.agent.engine.conversation import answered
from ov.agent.engine.prompt import system_prompt
from ov.agent.integrations.chat_completions import StreamResult, ignore
from ov.agent.integrations.common import Usage
from ov.agent.providers.base import ContextLimits, Initiator
from ov.agent.storage import db
from ov.agent.storage.models import UsageKind
from ov.agent.tools import tool_specs
from ov.agent.tools.browser import HANDS

if TYPE_CHECKING:
    from ov.agent.engine.run import Run

TOOL_WORKERS = 8
CONTEXT_TOKEN_KINDS = ("input", "cache_read", "cache_write", "output")
SUMMARY_READ_TIMEOUT_SECONDS = 300
EMPTY_REPLY_NOTE = "Your last reply was empty. Answer the user's last message."
SUMMARY_EMPTY = "{model} returned an empty summary, so the context was not compacted."
NOTHING_TO_COMPACT = "There is nothing to compact in this thread yet."
MIN_COMPACTABLE_MESSAGES = 3


class CompactionError(Exception):
    pass


class ChatBackend(Protocol):
    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        initiator: str,
        *,
        cancel: Cancel,
        on_text: Callable[[str], None],
        on_reasoning: Callable[[str], None] = ignore,
        reasoning: str | None = None,
    ) -> StreamResult: ...

    def complete(
        self, model: str, system: str, user_text: str, max_tokens: int, read_timeout: float
    ) -> tuple[str, Usage | None]: ...

    def token_limits(self, model: str) -> tuple[int, int, int]: ...

    def supports_vision(self, model: str) -> bool: ...

    def reasoning_for(self, model: str, wanted: str) -> str | None: ...


def limits(backend: ChatBackend, model: str) -> ContextLimits:
    window, prompt, output = backend.token_limits(model)
    return ContextLimits(window=window, prompt=prompt, output=output)


def valid_arguments(call: dict[str, Any]) -> bool:
    try:
        return isinstance(json.loads(call["function"]["arguments"] or "{}"), dict)
    except json.JSONDecodeError:
        return False


def repaired(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        call if valid_arguments(call) else {**call, "function": {**call["function"], "arguments": "{}"}}
        for call in calls
    ]


def has_context(run: Run) -> bool:
    return len(run.messages) >= MIN_COMPACTABLE_MESSAGES


def run_turn(backend: ChatBackend, run: Run, initiator: Initiator) -> None:
    model = run.model
    max_steps = int(db.get_preferences()["maxSteps"])
    run.vision = backend.supports_vision(model)
    run.finished = False
    nudged = False

    for step in range(max_steps):
        _prepare_step(backend, run, model)
        calls = _ask_model(backend, run, model, initiator if step == 0 else Initiator.AGENT)
        if calls:
            _run_tools(run, calls)
            if run.finished and not run.has_news():
                break
        elif not run.messages[-1].get("content") and not nudged:
            nudged = True
            run.add_note(EMPTY_REPLY_NOTE)
        elif not run.has_news():
            break


def _prepare_step(backend: ChatBackend, run: Run, model: str) -> None:
    run.cancel.check()
    if run.messages and run.messages[0]["role"] == "system":
        run.messages[0] = {"role": "system", "content": system_prompt(run.access, run.instance)}
    if run.context_tokens and run.context_tokens >= limits(backend, model).compact_at:
        summarize(backend, run, model, "auto")
    run.take_input()


def _ask_model(backend: ChatBackend, run: Run, model: str, initiator: Initiator) -> list[dict[str, Any]]:
    message_id = run.new_message_id()
    run.messages = answered(run.messages)
    for message in run.messages:
        if message.get("tool_calls"):
            message["tool_calls"] = repaired(message["tool_calls"])

    try:
        result = backend.stream_chat(
            model,
            run.messages,
            tool_specs(run.can_write()),
            initiator,
            cancel=run.cancel,
            on_text=lambda delta: run.stream_text(message_id, delta),
            on_reasoning=lambda delta: run.stream_reasoning(message_id, delta),
            reasoning=backend.reasoning_for(model, db.get_preferences()["reasoning"]),
        )
    finally:
        run.commit_text(message_id)

    run.record_usage(model, UsageKind.TURN if initiator == Initiator.USER else UsageKind.AGENT, result.usage)
    if result.usage is not None:
        run.context_tokens = sum(result.usage.tokens.get(kind, 0) for kind in CONTEXT_TOKEN_KINDS)
        known = limits(backend, model)
        run.record_context(run.context_tokens, known.prompt, known.compact_at)

    reply: dict[str, Any] = {"role": "assistant", "content": result.text or None}
    if result.tool_calls:
        run.mark_cut_off({c["id"] for c in result.tool_calls if not valid_arguments(c)})
        reply["tool_calls"] = repaired(result.tool_calls)

    run.messages.append(reply)
    run.persist()
    return result.tool_calls


def _run_tools(run: Run, calls: list[dict[str, Any]]) -> None:
    with ThreadPoolExecutor(max_workers=TOOL_WORKERS) as pool:
        outputs = list(pool.map(run.call_tool, calls))

    for call, content in zip(calls, outputs, strict=True):
        run.messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})

    images = run.take_images()
    if images:
        parts: list[dict[str, Any]] = [{"type": "text", "text": f"Attached: {', '.join(n for n, _ in images)}"}]
        parts += [{"type": "image_url", "image_url": {"url": url}} for _, url in images]
        run.messages.append({"role": "user", "content": parts})

    run.persist()


def summarize(backend: ChatBackend, run: Run, model: str, trigger: str) -> None:
    known = limits(backend, model)
    cut = compaction.cut_point(run.messages, int(known.compact_at * compaction.KEEP_RECENT_SHARE))
    if cut is None:
        raise CompactionError(NOTHING_TO_COMPACT)

    run.compaction_started(trigger)
    tools = tool_specs(run.can_write())
    before = run.context_tokens or compaction.estimate_tokens(run.messages, tools)
    summary, usage = backend.complete(
        model,
        compaction.SUMMARY_PROMPT,
        compaction.transcript(run.messages[1:cut]),
        compaction.SUMMARY_MAX_TOKENS,
        SUMMARY_READ_TIMEOUT_SECONDS,
    )
    run.record_usage(model, UsageKind.SUMMARY, usage)
    if not summary.strip():
        raise CompactionError(SUMMARY_EMPTY.format(model=model))

    run.messages = compaction.rebuilt(run.messages, cut, summary)
    run.turns = {turn: index - cut + 2 for turn, index in run.turns.items() if index >= cut}
    run.persist()
    run.context_tokens = compaction.estimate_tokens(run.messages, tools)
    run.compaction_finished(trigger, before, run.context_tokens)
    run.record_context(run.context_tokens, known.prompt, known.compact_at)


def drive_browser(backend: ChatBackend, run: Run, model: str, goal: str, cancel: Cancel) -> str:
    specs = [t.spec for t in HANDS]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": RUNNER_PROMPT},
        {"role": "user", "content": goal},
    ]

    for _ in range(RUNNER_STEPS):
        cancel.check()
        drop_old_pages(messages)

        result = backend.stream_chat(model, messages, specs, Initiator.AGENT, cancel=cancel, on_text=ignore)
        run.record_step_usage(model, result.usage)

        reply: dict[str, Any] = {"role": "assistant", "content": result.text or None}
        if result.tool_calls:
            reply["tool_calls"] = result.tool_calls
        messages.append(reply)
        if not result.tool_calls:
            return report(result.text)

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
