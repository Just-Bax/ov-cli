from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
)

from ov.agent.integrations.copilot import Usage
from ov.agent.storage.db import REASONING_LEVELS
from ov.core.paths import agent_dir

CLI = "claude"
AUTH_TIMEOUT_SECONDS = 30
ACCOUNT_TTL_SECONDS = 60
MODELS_TTL_SECONDS = 600
NANO_PER_USD = 1_000_000_000
HIDDEN_MODELS = frozenset({"default"})
HELPER_EFFORT = "low"
HELPER_DIR = "claude-helper"
MESSAGE_BUFFER_BYTES = 64 * 1024 * 1024
HELPER_QUESTIONS = 30
HELPER_TIMEOUT_SECONDS = 120
SERVER_NAME = "ov"
TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
SIGN_IN_HINT = "Install Claude Code, run `claude` in a terminal and sign in with /login."
NO_TRANSCRIPT = {"no-session-persistence": None}
TOKEN_FIELDS = {
    "input_tokens": "input",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
    "output_tokens": "output",
}


class ClaudeError(Exception):
    pass


_lock = threading.Lock()
_models: tuple[float, list[dict[str, Any]]] | None = None
_account: tuple[float, dict[str, Any]] | None = None


def cli_path() -> str:
    found = shutil.which(CLI)
    if found is None:
        raise ClaudeError(f"Claude Code is not installed. {SIGN_IN_HINT}")
    return found


def account() -> dict[str, Any]:
    global _account
    with _lock:
        if _account and time.time() - _account[0] < ACCOUNT_TTL_SECONDS:
            return _account[1]

    found = shutil.which(CLI)
    if found is None:
        return {"installed": False, "signedIn": False}

    result = subprocess.run(
        [found, "auth", "status"], capture_output=True, text=True, timeout=AUTH_TIMEOUT_SECONDS, check=False
    )

    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ClaudeError(f"claude auth status gave no account: {(result.stderr or result.stdout).strip()}") from None

    entry = {
        "installed": True,
        "signedIn": bool(status.get("loggedIn")),
        "email": status.get("email") or "",
        "plan": status.get("subscriptionType") or "",
        "method": status.get("authMethod") or "",
    }

    with _lock:
        _account = (time.time(), entry)

    return entry


def forget_account() -> None:
    global _account, _models
    with _lock:
        _account, _models = None, None


def _model_entry(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": model["value"],
        "name": model.get("displayName") or model["value"],
        "vendor": "Anthropic",
        "vision": True,
        "premium": None,
        "reasoning": [level for level in model.get("supportedEffortLevels") or [] if level in REASONING_LEVELS],
        "description": model.get("description") or "",
    }


async def _server_models() -> list[dict[str, Any]]:
    options = ClaudeAgentOptions(
        tools=[],
        setting_sources=[],
        cli_path=cli_path(),
        cwd=str(agent_dir(HELPER_DIR)),
        extra_args=dict(NO_TRANSCRIPT),
        max_buffer_size=MESSAGE_BUFFER_BYTES,
    )
    async with ClaudeSDKClient(options) as client:
        info = await client.get_server_info()

    if not info or not info.get("models"):
        raise ClaudeError(f"Claude Code listed no models. {SIGN_IN_HINT}")
    return [_model_entry(m) for m in info["models"] if m["value"] not in HIDDEN_MODELS]


def list_models() -> list[dict[str, Any]]:
    global _models
    with _lock:
        if _models and time.time() - _models[0] < MODELS_TTL_SECONDS:
            return _models[1]

    listed = asyncio.run(_server_models())

    with _lock:
        _models = (time.time(), listed)

    return listed


def effort_for(model_id: str, wanted: str) -> str | None:
    if not wanted:
        return None

    if wanted not in REASONING_LEVELS:
        raise ClaudeError(f"Unknown reasoning level: {wanted}")

    model = next((m for m in list_models() if m["id"] == model_id), None)
    if model is None or not model["reasoning"]:
        return None

    rank = REASONING_LEVELS.index(wanted)

    return min(
        model["reasoning"],
        key=lambda level: (abs(REASONING_LEVELS.index(level) - rank), -REASONING_LEVELS.index(level)),
    )


def usage_of(result: ResultMessage, spent_before: float) -> Usage:
    raw = result.usage or {}
    tokens = {name: int(raw.get(field) or 0) for field, name in TOKEN_FIELDS.items() if raw.get(field)}
    spent = max((result.total_cost_usd or 0) - spent_before, 0)
    return Usage(tokens=tokens, nano=int(spent * NANO_PER_USD))


def result_error(result: ResultMessage) -> str:
    detail = "; ".join(result.errors or []) or result.result or result.subtype
    return f"Claude Code stopped: {detail}"


def base_options(model: str, system: str, cwd: Path, effort: str | None) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        tools=[],
        setting_sources=[],
        system_prompt=system,
        model=model,
        effort=effort,
        cli_path=cli_path(),
        cwd=str(cwd),
        max_buffer_size=MESSAGE_BUFFER_BYTES,
    )


class _Helper:
    def __init__(self, model: str, system: str) -> None:
        self._model = model
        self._system = system
        self._loop = asyncio.new_event_loop()
        self._lock = asyncio.Lock()
        self._client: ClaudeSDKClient | None = None
        self._asked = 0
        self._spent = 0.0

        threading.Thread(target=self._loop.run_forever, name="claude-helper", daemon=True).start()

    def ask(self, text: str) -> tuple[str, Usage]:
        return asyncio.run_coroutine_threadsafe(self._ask(text), self._loop).result(HELPER_TIMEOUT_SECONDS)

    def close(self) -> None:
        asyncio.run_coroutine_threadsafe(self._close(), self._loop).result(HELPER_TIMEOUT_SECONDS)

    async def _ask(self, text: str) -> tuple[str, Usage]:
        async with self._lock:
            if self._client is None or self._asked >= HELPER_QUESTIONS:
                await self._open()

            self._asked += 1
            client = self._client
            await client.query(text)
            answer: ResultMessage | None = None
            async for message in client.receive_response():
                if isinstance(message, ResultMessage):
                    answer = message

            if answer is None or answer.is_error:
                await self._close()
                raise ClaudeError(result_error(answer) if answer else f"Claude Code gave no answer. {SIGN_IN_HINT}")

            usage = usage_of(answer, self._spent)
            self._spent = answer.total_cost_usd or self._spent
            return answer.result or "", usage

    async def _open(self) -> None:
        await self._close()
        options = base_options(self._model, self._system, agent_dir(HELPER_DIR), HELPER_EFFORT)
        options.max_turns = 1
        options.extra_args = dict(NO_TRANSCRIPT)

        self._client = ClaudeSDKClient(options)
        await self._client.connect()

        self._asked, self._spent = 0, 0.0

    async def _close(self) -> None:
        if self._client is None:
            return
        client, self._client = self._client, None
        await client.disconnect()


_helpers: dict[tuple[str, str], _Helper] = {}
_helpers_lock = threading.Lock()


def _helper(model: str, system: str) -> _Helper:
    with _helpers_lock:
        found = _helpers.get((model, system))
        if found is None:
            found = _helpers[(model, system)] = _Helper(model, system)
        return found


def close_helpers() -> None:
    with _helpers_lock:
        helpers = list(_helpers.values())
        _helpers.clear()
    for helper in helpers:
        helper.close()


def complete(model: str, system: str, user_text: str) -> tuple[str, Usage]:
    text, usage = _helper(model, system).ask(user_text)
    if not text.strip():
        raise ClaudeError(f"{model} returned an empty reply.")
    return text, usage
