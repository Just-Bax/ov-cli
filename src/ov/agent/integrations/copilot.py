from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from ov.agent.engine.cancel import Cancel, Cancelled
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
CHAT_READ_TIMEOUT_SECONDS = 300
MODELS_TTL_SECONDS = 600
TOKEN_REFRESH_MARGIN_SECONDS = 120
MAX_TOKENS = 32000
CHAT_ATTEMPTS = 4
COMPLETE_MAX_TOKENS = 200
RETRY_BASE_SECONDS = 2
ERROR_DETAIL_CHARS = 500
PENDING_STATUSES = {"authorization_pending": "pending", "slow_down": "slow_down"}


class CopilotError(Exception):
    pass


@dataclass
class Usage:
    tokens: dict[str, int]
    nano: int


@dataclass
class StreamResult:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage | None = None


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


def _usable(model: dict[str, Any]) -> bool:
    capabilities = model.get("capabilities") or {}
    return bool(
        capabilities.get("type") == "chat"
        and (capabilities.get("supports") or {}).get("tool_calls")
        and model.get("model_picker_enabled") is not False
        and (model.get("policy") or {}).get("state") != "disabled"
    )


def _model_entry(model: dict[str, Any]) -> dict[str, Any]:
    supports = model["capabilities"].get("supports") or {}
    return {
        "id": model["id"],
        "name": model.get("name") or model["id"],
        "vendor": model.get("vendor") or "",
        "vision": bool(supports.get("vision")),
        "premium": (model.get("billing") or {}).get("multiplier"),
        "reasoning": [level for level in supports.get("reasoning_effort") or [] if level in REASONING_LEVELS],
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


def supports_vision(model_id: str) -> bool:
    model = next((m for m in list_models() if m["id"] == model_id), None)
    if model is None:
        raise CopilotError(f"Model {model_id} is not available on this Copilot account.")
    return model["vision"]


def _has_images(messages: list[dict[str, Any]]) -> bool:
    return any(
        m["role"] == "user"
        and isinstance(m["content"], list)
        and any(p.get("type") == "image_url" for p in m["content"])
        for m in messages
    )


def _post(
    http: httpx.Client, url: str, headers: dict[str, str], payload: dict[str, Any], cancel: Cancel
) -> httpx.Response:
    cancel.check()
    request = http.build_request("POST", url, json=payload)
    request.headers.update(headers)
    return http.send(request, stream=True)


def _retryable(response: httpx.Response) -> bool:
    return response.status_code == 429 or response.status_code >= 500


def _send_with_retries(
    http: httpx.Client, url: str, headers: dict[str, str], payload: dict[str, Any], cancel: Cancel
) -> httpx.Response:
    for attempt in range(CHAT_ATTEMPTS - 1):
        try:
            response = _post(http, url, headers, payload, cancel)
        except httpx.TransportError:
            cancel.wait(RETRY_BASE_SECONDS * 2**attempt)
            continue
        if not _retryable(response):
            return response

        response.close()
        cancel.wait(RETRY_BASE_SECONDS * 2**attempt)
    return _post(http, url, headers, payload, cancel)


def stream_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    initiator: str,
    *,
    cancel: Cancel,
    on_text: Callable[[str], None],
    reasoning: str | None = None,
) -> StreamResult:
    extra = {"X-Initiator": initiator}
    if _has_images(messages):
        extra["Copilot-Vision-Request"] = "true"
    api, headers = _headers(**extra)
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

    streamed = False

    def forward(text: str) -> None:
        nonlocal streamed
        streamed = True
        on_text(text)

    for attempt in range(CHAT_ATTEMPTS):
        try:
            return _stream_once(api, headers, payload, cancel, forward)
        except httpx.TransportError as exc:
            if cancel.is_set():
                raise Cancelled from None
            if streamed or attempt == CHAT_ATTEMPTS - 1:
                raise CopilotError(f"Lost the connection to Copilot: {exc}. Send a message to continue.") from exc
            cancel.wait(RETRY_BASE_SECONDS * 2**attempt)
    raise CopilotError("Copilot chat retries ran out.")


def _stream_once(
    api: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    cancel: Cancel,
    on_text: Callable[[str], None],
) -> StreamResult:
    with httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS, read=CHAT_READ_TIMEOUT_SECONDS)) as http:
        response = _send_with_retries(http, f"{api}/chat/completions", headers, payload, cancel)
        with cancel.hook(response.close):
            if response.status_code >= 400:
                detail = response.read().decode("utf-8", "replace")[:ERROR_DETAIL_CHARS]
                raise CopilotError(f"Copilot chat failed ({response.status_code}): {detail}")
            try:
                return _read_stream(response, on_text)
            except httpx.HTTPError:
                if cancel.is_set():
                    raise Cancelled from None
                raise


def complete(
    model: str, system: str, user_text: str, max_tokens: int = COMPLETE_MAX_TOKENS
) -> tuple[str, Usage | None]:
    api, headers = _headers(**{"X-Initiator": "agent"})
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        "stream": False,
        "max_tokens": max_tokens,
    }

    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as http:
        response = http.post(f"{api}/chat/completions", json=payload, headers=headers)
    if response.status_code >= 400:
        raise CopilotError(f"Copilot chat failed ({response.status_code}): {response.text[:ERROR_DETAIL_CHARS]}")

    body = response.json()
    content = body["choices"][0]["message"].get("content")
    if not content:
        raise CopilotError(f"Copilot returned an empty reply from {model}.")
    return content.strip(), usage_of(body)


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


def _chunks(response: httpx.Response) -> Iterator[dict[str, Any]]:
    for line in response.iter_lines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped[len("data:") :].strip()
        if data == "[DONE]":
            continue
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            raise CopilotError(f"Copilot sent a malformed stream chunk: {data[:ERROR_DETAIL_CHARS]}") from None


def _merge_tool_call(calls: dict[tuple[int, int], dict[str, Any]], choice: int, part: dict[str, Any]) -> None:
    key = (choice, part.get("index") or 0)
    call = calls.setdefault(key, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    if part.get("id"):
        call["id"] = part["id"]
    function = part.get("function") or {}
    call["function"]["name"] += function.get("name") or ""
    call["function"]["arguments"] += function.get("arguments") or ""


def _read_stream(response: httpx.Response, on_text: Callable[[str], None]) -> StreamResult:
    result = StreamResult()
    calls: dict[tuple[int, int], dict[str, Any]] = {}
    for chunk in _chunks(response):
        result.usage = usage_of(chunk) or result.usage
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                result.text += delta["content"]
                on_text(delta["content"])
            for part in delta.get("tool_calls") or []:
                _merge_tool_call(calls, choice.get("index") or 0, part)

    stamp = int(time.time() * 1000)
    for index, call in enumerate(c for c in calls.values() if c["function"]["name"]):
        call["id"] = call["id"] or f"call_{stamp}_{index}"
        result.tool_calls.append(call)
    return result
