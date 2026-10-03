from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import credentials
from .cancel import Cancel, Cancelled

# The OAuth app VS Code's Copilot extension uses: Copilot only issues API tokens to
# OAuth tokens minted for a Copilot-enabled app.
CLIENT_ID = "Iv1.b507a08c87ecfe98"
EDITOR_HEADERS = {
    "Editor-Version": "vscode/1.104.0",
    "Editor-Plugin-Version": "copilot-chat/0.31.0",
    "User-Agent": "GitHubCopilotChat/0.31.0",
    "Copilot-Integration-Id": "vscode-chat",
}
CREDENTIAL_KEY = "github-copilot"
DEFAULT_API = "https://api.githubcopilot.com"
MODELS_TTL_SECONDS = 600


class CopilotError(Exception):
    pass


@dataclass
class StreamResult:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None


_lock = threading.Lock()
_token: dict[str, Any] | None = None
_models: tuple[float, list[dict[str, Any]]] | None = None


def _auth() -> dict[str, Any]:
    return credentials.get(CREDENTIAL_KEY) or {}


def user() -> str | None:
    auth = _auth()
    return (auth.get("user") or "signed in") if auth.get("github_token") else None


def sign_out() -> None:
    global _token, _models
    credentials.delete(CREDENTIAL_KEY)
    with _lock:
        _token, _models = None, None


def start_device_flow() -> dict[str, Any]:
    response = httpx.post(
        "https://github.com/login/device/code",
        headers={"Accept": "application/json"},
        json={"client_id": CLIENT_ID, "scope": "read:user"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise CopilotError(f"GitHub device code request failed: {response.status_code}")
    body = response.json()
    return {
        "deviceCode": body["device_code"],
        "userCode": body["user_code"],
        "verificationUri": body["verification_uri"],
        "interval": body.get("interval", 5),
        "expiresIn": body.get("expires_in", 900),
    }


def poll_device_flow(device_code: str) -> dict[str, Any]:
    global _token
    response = httpx.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        json={
            "client_id": CLIENT_ID,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        timeout=30,
    )
    body = response.json()
    if body.get("access_token"):
        login = _github_login(body["access_token"])
        credentials.put(CREDENTIAL_KEY, {"github_token": body["access_token"], "user": login})
        with _lock:
            _token = None
        _copilot_token()
        return {"status": "ok", "user": login}
    if body.get("error") in ("authorization_pending", "slow_down"):
        return {"status": "pending" if body["error"] == "authorization_pending" else "slow_down"}
    return {
        "status": "error",
        "message": body.get("error_description") or body.get("error") or "unknown error",
    }


def _github_login(token: str) -> str | None:
    response = httpx.get(
        "https://api.github.com/user",
        headers={"Authorization": f"token {token}", "User-Agent": "ov-agent"},
        timeout=30,
    )
    return response.json().get("login") if response.status_code < 400 else None


def _copilot_token() -> dict[str, Any]:
    global _token
    with _lock:
        if _token and _token["expires_at"] - 120 > time.time():
            return _token

    github_token = _auth().get("github_token")
    if not github_token:
        raise CopilotError("Not signed in to GitHub Copilot. Open Setup to sign in.")
    response = httpx.get(
        "https://api.github.com/copilot_internal/v2/token",
        headers={"Authorization": f"token {github_token}", **EDITOR_HEADERS},
        timeout=30,
    )
    if response.status_code == 401:
        sign_out()
        raise CopilotError("GitHub sign-in expired. Open Setup to sign in again.")
    if response.status_code >= 400:
        raise CopilotError(
            f"Copilot token exchange failed ({response.status_code}). "
            "Does this GitHub account have Copilot?"
        )

    body = response.json()
    token = {
        "token": body["token"],
        "expires_at": float(body.get("expires_at") or time.time() + 600),
        "api": (body.get("endpoints") or {}).get("api") or DEFAULT_API,
    }
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


def list_models() -> list[dict[str, Any]]:
    global _models
    with _lock:
        if _models and time.time() - _models[0] < MODELS_TTL_SECONDS:
            return _models[1]

    api, headers = _headers()
    response = httpx.get(f"{api}/models", headers=headers, timeout=30)
    if response.status_code >= 400:
        raise CopilotError(f"Copilot /models failed: {response.status_code}")

    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in response.json().get("data", []):
        capabilities = model.get("capabilities") or {}
        supports = capabilities.get("supports") or {}
        usable = (
            capabilities.get("type") == "chat"
            and supports.get("tool_calls")
            and model.get("model_picker_enabled") is not False
            and (model.get("policy") or {}).get("state") != "disabled"
        )
        if not usable or model["id"] in seen:
            continue
        seen.add(model["id"])
        models.append(
            {
                "id": model["id"],
                "name": model.get("name") or model["id"],
                "vendor": model.get("vendor") or "",
                "vision": bool(supports.get("vision")),
                "premium": (model.get("billing") or {}).get("multiplier"),
            }
        )
    with _lock:
        _models = (time.time(), models)
    return models


def supports_vision(model_id: str) -> bool:
    try:
        models = list_models()
    except Exception:
        return True
    return next((m["vision"] for m in models if m["id"] == model_id), True)


def stream_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    initiator: str,
    cancel: Cancel,
    on_text: Callable[[str], None],
) -> StreamResult:
    has_images = any(
        m["role"] == "user"
        and isinstance(m["content"], list)
        and any(p.get("type") == "image_url" for p in m["content"])
        for m in messages
    )
    extra = {"X-Initiator": initiator}
    if has_images:
        extra["Copilot-Vision-Request"] = "true"
    api, headers = _headers(**extra)
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "stream": True,
        "max_tokens": 16000,
    }

    with httpx.Client(timeout=httpx.Timeout(30, read=300)) as http:
        for attempt in range(4):
            cancel.check()
            request = http.build_request("POST", f"{api}/chat/completions", json=payload)
            request.headers.update(headers)
            response = http.send(request, stream=True)
            with cancel.hook(response.close):
                retryable = response.status_code == 429 or response.status_code >= 500
                if retryable and attempt < 3:
                    response.close()
                    cancel.wait(2 * 2**attempt)
                    continue
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", "replace")[:500]
                    raise CopilotError(f"Copilot chat failed ({response.status_code}): {detail}")
                try:
                    return _read_stream(response, on_text)
                except httpx.HTTPError:
                    if cancel.is_set():
                        raise Cancelled from None
                    raise
    raise CopilotError("Copilot chat failed after retries.")


def _read_stream(response: httpx.Response, on_text: Callable[[str], None]) -> StreamResult:
    result = StreamResult()
    calls: dict[tuple[int, int], dict[str, Any]] = {}
    for line in response.iter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            continue
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue

        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason"):
                result.finish_reason = choice["finish_reason"]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                result.text += delta["content"]
                on_text(delta["content"])
            # Some models put each call under its own choice index, others share one choice.
            for part in delta.get("tool_calls") or []:
                key = (choice.get("index") or 0, part.get("index") or 0)
                call = calls.setdefault(
                    key, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if part.get("id"):
                    call["id"] = part["id"]
                function = part.get("function") or {}
                call["function"]["name"] += function.get("name") or ""
                call["function"]["arguments"] += function.get("arguments") or ""

    stamp = int(time.time() * 1000)
    for index, call in enumerate(c for c in calls.values() if c["function"]["name"]):
        call["id"] = call["id"] or f"call_{stamp}_{index}"
        result.tool_calls.append(call)
    return result
