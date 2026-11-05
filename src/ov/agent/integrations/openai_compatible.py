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
from ov.agent.storage.db import NANO_PER_UNIT
from ov.core import credentials

NAME = "vLLM"
CREDENTIAL_KEY = "openai-compatible"
HTTP_TIMEOUT_SECONDS = 30
MODELS_TTL_SECONDS = 60
OUTPUT_RESERVE_TOKENS = 8192
HELPER_REASONING_TOKENS = 4096
MIN_CONTEXT_TOKENS = 32_768
ERROR_DETAIL_CHARS = 300
URL_SCHEMES = ("http://", "https://")
NOT_CONNECTED = f"{NAME} is not connected. Add its base URL in Settings."
NO_USAGE = (
    "The server sent no token usage with its reply, so the agent cannot tell how full the context is. "
    "Use a server that reports usage in streamed replies (vLLM does)."
)


class OpenAICompatibleError(Exception):
    pass


_lock = threading.Lock()
_models: tuple[float, list[dict[str, Any]]] | None = None


def _forget_models() -> None:
    global _models
    with _lock:
        _models = None


def _stored() -> dict[str, Any] | None:
    return credentials.get(CREDENTIAL_KEY)


def _required() -> dict[str, Any]:
    stored = _stored()
    if stored is None:
        raise OpenAICompatibleError(NOT_CONNECTED)
    return stored


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def base_url_of(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url.startswith(URL_SCHEMES):
        raise OpenAICompatibleError(
            f"The base URL must start with http:// or https://, like http://host:8000/v1: {value}"
        )
    return url


def _served(base_url: str, api_key: str) -> list[dict[str, Any]]:
    try:
        response = httpx.get(f"{base_url}/models", headers=_headers(api_key), timeout=HTTP_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise OpenAICompatibleError(f"Could not reach {base_url}: {exc}") from None

    if response.status_code == httpx.codes.NOT_FOUND:
        raise OpenAICompatibleError(f"{base_url}/models was not found. The base URL usually ends with /v1.")

    if response.status_code >= httpx.codes.BAD_REQUEST:
        detail = response.text[:ERROR_DETAIL_CHARS]
        raise OpenAICompatibleError(f"{base_url}/models failed ({response.status_code}): {detail}")

    served = response.json().get("data")
    if not served:
        raise OpenAICompatibleError(f"{base_url} serves no models.")
    return served


def account() -> dict[str, Any]:
    stored = _stored()
    if stored is None:
        return {"signedIn": False, "baseUrl": None, "hasKey": False}
    return {"signedIn": True, "baseUrl": stored["baseUrl"], "hasKey": bool(stored["apiKey"])}


def connect(base_url: str, api_key: str) -> dict[str, Any]:
    url = base_url_of(base_url)
    key = api_key.strip()
    _served(url, key)

    previous = _stored()
    kept = previous["models"] if previous and previous["baseUrl"] == url else {}
    credentials.put(CREDENTIAL_KEY, {"baseUrl": url, "apiKey": key, "models": kept})
    _forget_models()
    return account()


def disconnect() -> dict[str, Any]:
    credentials.delete(CREDENTIAL_KEY)
    _forget_models()
    return account()


def configure_model(model_id: str, vision: bool, context_window: int | None) -> list[dict[str, Any]]:
    stored = _required()
    if model_id not in {m["id"] for m in list_models()}:
        raise OpenAICompatibleError(f"{stored['baseUrl']} does not serve {model_id}.")

    if context_window is not None and context_window < MIN_CONTEXT_TOKENS:
        raise OpenAICompatibleError(f"The agent needs a context window of at least {MIN_CONTEXT_TOKENS} tokens.")

    models = {**stored["models"], model_id: {"vision": vision, "contextWindow": context_window}}
    credentials.put(CREDENTIAL_KEY, {**stored, "models": models})
    _forget_models()
    return list_models()


def _model_entry(served: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    reported = served.get("max_model_len")
    window = settings.get("contextWindow") or reported

    return {
        "id": served["id"],
        "name": served["id"],
        "vendor": served.get("owned_by") or "",
        "vision": bool(settings.get("vision")),
        "premium": None,
        "reasoning": [],
        "contextWindow": window,
        "windowTokens": window,
        "outputTokens": OUTPUT_RESERVE_TOKENS,
        "reportedWindow": reported,
    }


def list_models() -> list[dict[str, Any]]:
    global _models
    with _lock:
        if _models and time.time() - _models[0] < MODELS_TTL_SECONDS:
            return _models[1]

    stored = _required()
    settings = stored["models"]
    listed = [_model_entry(m, settings.get(m["id"], {})) for m in _served(stored["baseUrl"], stored["apiKey"])]

    with _lock:
        _models = (time.time(), listed)

    return listed


def _model(model_id: str) -> dict[str, Any]:
    found = next((m for m in list_models() if m["id"] == model_id), None)
    if found is None:
        raise OpenAICompatibleError(f"{model_id} is not served by {_required()['baseUrl']}.")
    return found


def token_limits(model_id: str) -> tuple[int, int, int]:
    window = _model(model_id)["windowTokens"]
    if not window:
        raise OpenAICompatibleError(
            f"The server does not say how much context {model_id} takes. Set its context window in Settings > Accounts."
        )

    if window < MIN_CONTEXT_TOKENS:
        raise OpenAICompatibleError(
            f"{model_id} has a {window}-token context window; the agent needs at least {MIN_CONTEXT_TOKENS}."
        )

    return int(window), int(window), OUTPUT_RESERVE_TOKENS


def supports_vision(model_id: str) -> bool:
    return bool(_model(model_id)["vision"])


def reasoning_for(_model_id: str, _wanted: str) -> str | None:
    return None


def usage_of(body: dict[str, Any]) -> Usage | None:
    usage = body.get("usage")
    if not usage:
        return None

    prompt = int(usage.get("prompt_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    output = int(usage.get("completion_tokens") or 0)
    tokens = {"input": prompt - cached, "cache_read": cached, "output": output}
    return Usage(tokens=tokens, nano=(prompt + output) * NANO_PER_UNIT)


def _endpoint() -> chat_completions.Endpoint:
    stored = _required()
    return chat_completions.Endpoint(
        name=NAME,
        url=stored["baseUrl"],
        headers=_headers(stored["apiKey"]),
        error=OpenAICompatibleError,
        usage_of=usage_of,
    )


def stream_chat(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    _initiator: str,
    *,
    cancel: Cancel,
    on_text: Callable[[str], None],
    on_reasoning: Callable[[str], None] = chat_completions.ignore,
    reasoning: str | None = None,
) -> StreamResult:
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "stream": True,
        "stream_options": {"include_usage": True},
        **({"reasoning_effort": reasoning} if reasoning else {}),
    }
    result = chat_completions.stream(_endpoint(), payload, cancel=cancel, on_text=on_text, on_reasoning=on_reasoning)
    if result.usage is None:
        raise OpenAICompatibleError(NO_USAGE)
    return result


def complete(model: str, system: str, user_text: str, max_tokens: int, read_timeout: float) -> tuple[str, Usage | None]:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        "stream": False,
        "max_tokens": max_tokens + HELPER_REASONING_TOKENS,
    }
    return chat_completions.complete(_endpoint(), payload, read_timeout)
