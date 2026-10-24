from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from ov.agent.engine.cancel import Cancel
from ov.agent.integrations import chat_completions
from ov.agent.integrations.chat_completions import StreamResult
from ov.agent.integrations.common import Usage
from ov.agent.storage.db import REASONING_LEVELS
from ov.core import credentials

CLIENT_ID = "Iv1.b507a08c87ecfe98"
EDITOR_HEADERS = {
    "Editor-Version": "vscode/1.104.0",
    "Editor-Plugin-Version": "copilot-chat/0.31.0",
    "User-Agent": "GitHubCopilotChat/0.31.0",
    "Copilot-Integration-Id": "vscode-chat",
}
CREDENTIAL_KEY = "github-copilot"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
COPILOT_USER_URL = "https://api.github.com/copilot_internal/user"
HTTP_TIMEOUT_SECONDS = 30
MODELS_TTL_SECONDS = 600
TOKEN_REFRESH_MARGIN_SECONDS = 120
MAX_TOKENS = 32000
COMPLETE_MAX_TOKENS = 200
PENDING_STATUSES = {"authorization_pending": "pending", "slow_down": "slow_down"}


class CopilotError(Exception):
    pass


def usage_of(body: dict[str, Any]) -> Usage | None:
    billed = body.get("copilot_usage")
    if not billed:
        return None

    tokens: dict[str, int] = {}
    for detail in billed.get("token_details") or []:
        tokens[detail["token_type"]] = tokens.get(detail["token_type"], 0) + int(detail["token_count"])

    return Usage(tokens=tokens, nano=int(billed["total_nano_aiu"]))


_lock = threading.Lock()
_token: dict[str, Any] | None = None
_models: tuple[float, list[dict[str, Any]]] | None = None


def user() -> str | None:
    auth = credentials.get(CREDENTIAL_KEY)
    return auth["user"] if auth else None


def sign_out() -> None:
    global _token, _models
    credentials.delete(CREDENTIAL_KEY)
    with _lock:
        _token, _models = None, None


def start_device_flow() -> dict[str, Any]:
    response = httpx.post(
        DEVICE_CODE_URL,
        headers={"Accept": "application/json"},
        json={"client_id": CLIENT_ID, "scope": "read:user"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise CopilotError(f"GitHub device code request failed: {response.status_code}")

    body = response.json()

    return {
        "deviceCode": body["device_code"],
        "userCode": body["user_code"],
        "verificationUri": body["verification_uri"],
        "interval": body["interval"],
        "expiresIn": body["expires_in"],
    }


def poll_device_flow(device_code: str) -> dict[str, Any]:
    global _token
    response = httpx.post(
        ACCESS_TOKEN_URL,
        headers={"Accept": "application/json"},
        json={
            "client_id": CLIENT_ID,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    body = response.json()
    if body.get("access_token"):
        login = _github_login(body["access_token"])
        credentials.put(CREDENTIAL_KEY, {"github_token": body["access_token"], "user": login})
        with _lock:
            _token = None

        _copilot_token()
        return {"status": "ok", "user": login}

    error = body.get("error")
    if error in PENDING_STATUSES:
        return {"status": PENDING_STATUSES[error]}

    if error is None:
        raise CopilotError(f"GitHub sign-in returned neither a token nor an error ({response.status_code}).")

    return {"status": "error", "message": body.get("error_description") or error}


def _github_login(token: str) -> str:
    response = httpx.get(
        GITHUB_USER_URL,
        headers={"Authorization": f"token {token}", "User-Agent": "ov-agent"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise CopilotError(f"Reading the GitHub user failed: {response.status_code}")
    return response.json()["login"]


def _copilot_token() -> dict[str, Any]:
    global _token
    with _lock:
        if _token and _token["expires_at"] - TOKEN_REFRESH_MARGIN_SECONDS > time.time():
            return _token

    auth = credentials.get(CREDENTIAL_KEY)
    if auth is None:
        raise CopilotError("Not signed in to GitHub Copilot. Open Setup to sign in.")

    response = httpx.get(
        COPILOT_TOKEN_URL,
        headers={"Authorization": f"token {auth['github_token']}", **EDITOR_HEADERS},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code == 401:
        sign_out()
        raise CopilotError("GitHub sign-in expired. Open Setup to sign in again.")

    if response.status_code >= 400:
        raise CopilotError(
            f"Copilot token exchange failed ({response.status_code}). Does this GitHub account have Copilot?"
        )

    body = response.json()
    token = {"token": body["token"], "expires_at": float(body["expires_at"]), "api": body["endpoints"]["api"]}

    with _lock:
        _token = token

    return token


def _headers(**extra: str) -> tuple[str, dict[str, str]]:
    token = _copilot_token()

    headers = {
        "Authorization": f"Bearer {token['token']}",
        "Content-Type": "application/json",
        "Openai-Intent": "conversation-edits",
        **EDITOR_HEADERS,
        **extra,
    }
    return token["api"], headers


def _speaks_chat(model: dict[str, Any]) -> bool:
    endpoints = model.get("supported_endpoints")
    return endpoints is None or chat_completions.CHAT_PATH in endpoints


def _usable(model: dict[str, Any]) -> bool:
    capabilities = model.get("capabilities") or {}

    return bool(
        capabilities.get("type") == "chat"
        and (capabilities.get("supports") or {}).get("tool_calls")
        and _speaks_chat(model)
        and model.get("model_picker_enabled") is not False
        and (model.get("policy") or {}).get("state") != "disabled"
    )


def _model_entry(model: dict[str, Any]) -> dict[str, Any]:
    supports = model["capabilities"].get("supports") or {}
    limits = model["capabilities"].get("limits") or {}

    return {
        "id": model["id"],
        "name": model.get("name") or model["id"],
        "vendor": model.get("vendor") or "",
        "vision": bool(supports.get("vision")),
        "premium": (model.get("billing") or {}).get("multiplier"),
        "reasoning": [level for level in supports.get("reasoning_effort") or [] if level in REASONING_LEVELS],
        "contextWindow": limits.get("max_prompt_tokens"),
        "windowTokens": limits.get("max_context_window_tokens"),
        "outputTokens": limits.get("max_output_tokens"),
    }


def list_models() -> list[dict[str, Any]]:
    global _models
    with _lock:
        if _models and time.time() - _models[0] < MODELS_TTL_SECONDS:
            return _models[1]

    api, headers = _headers()
    response = httpx.get(f"{api}/models", headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
    if response.status_code >= 400:
        raise CopilotError(f"Copilot /models failed: {response.status_code}")

    models: dict[str, dict[str, Any]] = {}
    for model in response.json()["data"]:
        if _usable(model) and model["id"] not in models:
            models[model["id"]] = _model_entry(model)

    listed = list(models.values())

    with _lock:
        _models = (time.time(), listed)

    return listed


def reasoning_for(model_id: str, wanted: str) -> str | None:
    if not wanted:
        return None

    if wanted not in REASONING_LEVELS:
        raise CopilotError(f"Unknown reasoning level: {wanted}")

    model = next((m for m in list_models() if m["id"] == model_id), None)
    if model is None or not model["reasoning"]:
        return None

    rank = REASONING_LEVELS.index(wanted)

    return min(
        model["reasoning"],
        key=lambda level: (abs(REASONING_LEVELS.index(level) - rank), -REASONING_LEVELS.index(level)),
    )


def token_limits(model_id: str) -> tuple[int, int, int]:
    model = next((m for m in list_models() if m["id"] == model_id), None)
    if model is None:
        raise CopilotError(f"Model {model_id} is not available on this Copilot account.")
    if not (model["contextWindow"] and model["windowTokens"] and model["outputTokens"]):
        raise CopilotError(f"Copilot does not say how much context {model_id} takes.")
    return int(model["windowTokens"]), int(model["contextWindow"]), int(model["outputTokens"])


def supports_vision(model_id: str) -> bool:
    model = next((m for m in list_models() if m["id"] == model_id), None)
    if model is None:
        raise CopilotError(f"Model {model_id} is not available on this Copilot account.")
    return model["vision"]


def _endpoint(**extra: str) -> chat_completions.Endpoint:
    api, headers = _headers(**extra)
    return chat_completions.Endpoint(name="Copilot", url=api, headers=headers, error=CopilotError, usage_of=usage_of)


def stream_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    initiator: str,
    *,
    cancel: Cancel,
    on_text: Callable[[str], None],
    on_reasoning: Callable[[str], None] = chat_completions.ignore,
    reasoning: str | None = None,
) -> StreamResult:
    extra = {"X-Initiator": initiator}
    if chat_completions.has_images(messages):
        extra["Copilot-Vision-Request"] = "true"

    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": MAX_TOKENS,
        **({"reasoning_effort": reasoning} if reasoning else {}),
    }
    return chat_completions.stream(
        _endpoint(**extra), payload, cancel=cancel, on_text=on_text, on_reasoning=on_reasoning
    )


def complete(
    model: str,
    system: str,
    user_text: str,
    max_tokens: int = COMPLETE_MAX_TOKENS,
    read_timeout: float = HTTP_TIMEOUT_SECONDS,
) -> tuple[str, Usage | None]:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        "stream": False,
        "max_tokens": max_tokens,
    }
    return chat_completions.complete(_endpoint(**{"X-Initiator": "agent"}), payload, read_timeout)


def account() -> dict[str, Any]:
    auth = credentials.get(CREDENTIAL_KEY)
    if auth is None:
        raise CopilotError("Not signed in to GitHub Copilot. Open Setup to sign in.")

    response = httpx.get(
        COPILOT_USER_URL,
        headers={"Authorization": f"token {auth['github_token']}", **EDITOR_HEADERS},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise CopilotError(f"GitHub did not return Copilot usage ({response.status_code}).")

    body = response.json()
    premium = body["quota_snapshots"]["premium_interactions"]

    return {
        "plan": body.get("copilot_plan") or "",
        "resetDate": body.get("quota_reset_date") or None,
        "tokenBased": bool(premium.get("token_based_billing")),
        "creditsUsed": premium.get("credits_used"),
        "unlimited": bool(premium.get("unlimited")),
        "entitlement": premium.get("entitlement"),
        "remaining": premium.get("remaining"),
    }
