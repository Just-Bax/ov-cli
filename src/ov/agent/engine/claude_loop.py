from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    UserMessage,
    create_sdk_mcp_server,
    delete_session,
    get_session_messages,
    tool,
)

from ov.agent.engine.prompt import system_prompt
from ov.agent.integrations import claude
from ov.agent.storage import db
from ov.agent.tools import tool_specs

if TYPE_CHECKING:
    from ov.agent.engine.run import Run

REPLAY_PROMPTS = {"replay-user-messages": None}
ERROR_PREFIX = "Error:"
DATA_URL_PREFIX = "data:"
COMPACT_WINDOW_ENV = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
COMPACT_COMMAND = "/compact"
COMPACTING = "compacting"
COMPACT_SUCCESS = "success"
COMPACT_FAILED = "Claude Code could not compact the context ({result})."
COMPACT_UNREPORTED = "Claude Code finished without compacting the context."


def _image_block(url: str) -> dict[str, Any]:
    header, _, data = url.partition(",")
    if not header.startswith(DATA_URL_PREFIX) or not data:
        raise claude.ClaudeError("Only inline images can be sent to Claude.")
    media_type = header[len(DATA_URL_PREFIX) :].split(";", 1)[0]
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def content_blocks(contents: list[Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for content in contents:
        if isinstance(content, str):
            blocks.append({"type": "text", "text": content})
            continue
        for part in content:
            if part["type"] == "text":
                blocks.append({"type": "text", "text": part["text"]})
            else:
                blocks.append(_image_block(part["image_url"]["url"]))
    return blocks


def _tool_reply(text: str, images: list[tuple[str, str]]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for _, url in images:
        header, _, data = url.partition(",")
        content.append({"type": "image", "data": data, "mimeType": header[len(DATA_URL_PREFIX) :].split(";", 1)[0]})
    return {"content": content, "is_error": text.startswith(ERROR_PREFIX)}


def tool_handler(run: Run, name: str) -> Any:
    async def handle(args: dict[str, Any]) -> dict[str, Any]:
        text, images = await asyncio.to_thread(run.call_tool_with_steering, name, args)
        return _tool_reply(text, images)

    return handle


def tool_server(run: Run) -> Any:
    tools = [
        tool(spec["function"]["name"], spec["function"]["description"], spec["function"]["parameters"])(
            tool_handler(run, spec["function"]["name"])
        )
        for spec in tool_specs(run.can_write())
    ]
    return create_sdk_mcp_server(claude.SERVER_NAME, tools=tools)


def _last_uuid(session: str | None, cwd: str) -> str | None:
    if session is None:
        return None
    messages = get_session_messages(session, directory=cwd)
    return messages[-1].uuid if messages else None


def _options(run: Run) -> tuple[Any, str, dict[str, Any] | None]:
    model = run.state["summary"]["model"]
    options = claude.base_options(
        model,
        system_prompt(run.access, run.instance),
        run.work_dir,
        claude.effort_for(model, db.get_preferences()["reasoning"]),
    )
    options.mcp_servers = {claude.SERVER_NAME: tool_server(run)}
    options.allowed_tools = [f"{claude.TOOL_PREFIX}*"]
    options.include_partial_messages = True
    preferences = db.get_preferences()
    options.max_turns = int(preferences["maxSteps"])
    options.extra_args = dict(REPLAY_PROMPTS)
    if preferences["compactWindow"]:
        options.env = {COMPACT_WINDOW_ENV: str(preferences["compactWindow"])}

    fork = run.take_claude_fork()
    current = run.state["claude"]["session"]
    if fork is not None and fork.get("before"):
        session = str(uuid.uuid4())
        options.resume, options.fork_session, options.session_id = fork["session"], True, session
        options.resume_session_at, options.resume_drops_turn = fork["before"], fork["prompt"]
        return options, session, fork
    if current is None or fork is not None:
        session = str(uuid.uuid4())
        options.session_id = session
        return options, session, None

    options.resume = current
    return options, current, None


async def _prompt(blocks: list[dict[str, Any]], session: str) -> AsyncIterator[dict[str, Any]]:
    yield {
        "type": "user",
        "message": {"role": "user", "content": blocks},
        "parent_tool_use_id": None,
        "session_id": session,
    }


class Stream:
    def __init__(self, run: Run, session: str, turn: str | None, before: str | None) -> None:
        self.run = run
        self.session = session
        self.turn = turn
        self.before = before
        self.message_id: str | None = None
        self.prompt_seen = False

    def on_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "message_start":
            self.message_id = self.run.new_message_id()
        elif kind == "content_block_delta" and event["delta"].get("type") == "text_delta" and self.message_id:
            self.run.stream_text(self.message_id, event["delta"]["text"])
        elif kind == "message_stop" and self.message_id:
            self.run.commit_text(self.message_id)
            self.message_id = None

    def on_prompt(self, message: UserMessage) -> None:
        if self.prompt_seen or message.parent_tool_use_id is not None or not message.uuid:
            return
        self.prompt_seen = True
        anchor = {
            "session": self.session,
            "turn": self.turn,
            "prompt": message.uuid,
            "before": self.before,
            "spentBefore": self.run.state["claude"]["spent"],
        }
        self.run.emit({"type": "meta", "claude": anchor})

    def on_result(self, result: ResultMessage) -> None:
        if self.message_id:
            self.run.commit_text(self.message_id)
            self.message_id = None
        self.run.record_claude_usage(self.session, result)
        if result.is_error and not self.run.cancel.is_set():
            raise claude.ClaudeError(claude.result_error(result))


def on_system(run: Run, message: SystemMessage, trigger: str) -> None:
    data = message.data
    if message.subtype == "status" and data.get("status") == COMPACTING:
        run.compaction_started(trigger)
    elif message.subtype == "status" and data.get("compact_result") not in (None, COMPACT_SUCCESS):
        run.compaction_failed(COMPACT_FAILED.format(result=data["compact_result"]))
    elif message.subtype == "compact_boundary":
        meta = data["compact_metadata"]
        run.compaction_finished(meta["trigger"], int(meta["pre_tokens"]), int(meta.get("post_tokens") or 0))


async def _record_context(client: ClaudeSDKClient, run: Run) -> None:
    usage = await client.get_context_usage()
    run.record_context(int(usage["totalTokens"]), int(usage["rawMaxTokens"]), usage.get("autoCompactThreshold"))


async def _receive(client: ClaudeSDKClient, stream: Stream) -> None:
    async for message in client.receive_response():
        if isinstance(message, StreamEvent) and message.parent_tool_use_id is None:
            stream.on_event(message.event)
        elif isinstance(message, UserMessage):
            stream.on_prompt(message)
        elif isinstance(message, SystemMessage):
            on_system(stream.run, message, "auto")
        elif isinstance(message, ResultMessage):
            stream.on_result(message)


async def _session(run: Run, options: Any, session: str, fork_point: str | None) -> None:
    loop = asyncio.get_running_loop()
    async with ClaudeSDKClient(options) as client:

        def interrupt() -> None:
            asyncio.run_coroutine_threadsafe(client.interrupt(), loop)

        with run.cancel.hook(interrupt):
            while True:
                turn, contents = run.claude_input()
                if not contents:
                    return
                before = fork_point or _last_uuid(session, str(run.work_dir))
                fork_point = None
                await client.query(_prompt(content_blocks(contents), session))
                await _receive(client, Stream(run, session, turn, before))
                await _record_context(client, run)
                run.cancel.check()
                if not run.has_news():
                    return


def run_turn(run: Run) -> None:
    options, session, fork = _options(run)
    if session != run.state["claude"]["session"]:
        spent = fork.get("spentBefore", 0.0) if fork else 0.0
        run.emit({"type": "meta", "claude": {"session": session, "spent": spent}})
    asyncio.run(_session(run, options, session, fork["before"] if fork else None))


async def _compact(run: Run, options: Any, session: str) -> None:
    loop = asyncio.get_running_loop()
    async with ClaudeSDKClient(options) as client:

        def interrupt() -> None:
            asyncio.run_coroutine_threadsafe(client.interrupt(), loop)

        with run.cancel.hook(interrupt):
            run.compaction_started("manual")
            await client.query(COMPACT_COMMAND)
            async for message in client.receive_response():
                if isinstance(message, SystemMessage):
                    on_system(run, message, "manual")
                elif isinstance(message, ResultMessage):
                    run.record_claude_usage(session, message)
                    if message.is_error and not run.cancel.is_set():
                        raise claude.ClaudeError(claude.result_error(message))
            run.cancel.check()
            run.compaction_failed(COMPACT_UNREPORTED)
            await _record_context(client, run)


def compact(run: Run) -> None:
    options, session, _ = _options(run)
    asyncio.run(_compact(run, options, session))


def sessions_of(events: list[dict[str, Any]]) -> set[str]:
    return {
        e["event"]["claude"]["session"] for e in events if e["event"]["type"] == "meta" and e["event"].get("claude")
    }


def forget_sessions(sessions: set[str], cwd: str) -> None:
    for session in sessions:
        if get_session_messages(session, directory=cwd):
            delete_session(session, directory=cwd)
