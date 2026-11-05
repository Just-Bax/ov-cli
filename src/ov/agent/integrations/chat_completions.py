from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from ov.agent.engine.cancel import Cancel, Cancelled
from ov.agent.integrations.common import Usage

HTTP_TIMEOUT_SECONDS = 30
CHAT_READ_TIMEOUT_SECONDS = 300
CHAT_ATTEMPTS = 4
RETRY_BASE_SECONDS = 2
RETRY_BACKOFF_FACTOR = 2
ERROR_DETAIL_CHARS = 500
CHAT_PATH = "/chat/completions"
REASONING_KEYS = ("reasoning_content", "reasoning")


@dataclass
class StreamResult:
    text: str = ""
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage | None = None


@dataclass(frozen=True)
class Endpoint:
    name: str
    url: str
    headers: dict[str, str]
    error: type[Exception]
    usage_of: Callable[[dict[str, Any]], Usage | None]


def ignore(_: str) -> None:
    return None


def has_images(messages: list[dict[str, Any]]) -> bool:
    return any(
        m["role"] == "user"
        and isinstance(m["content"], list)
        and any(p.get("type") == "image_url" for p in m["content"])
        for m in messages
    )


def _post(http: httpx.Client, endpoint: Endpoint, payload: dict[str, Any], cancel: Cancel) -> httpx.Response:
    cancel.check()
    request = http.build_request("POST", endpoint.url + CHAT_PATH, json=payload)
    request.headers.update(endpoint.headers)
    return http.send(request, stream=True)


def _retryable(response: httpx.Response) -> bool:
    return (
        response.status_code == httpx.codes.TOO_MANY_REQUESTS
        or response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR
    )


def _backoff_seconds(attempt: int) -> float:
    return RETRY_BASE_SECONDS * RETRY_BACKOFF_FACTOR**attempt


def _send_with_retries(
    http: httpx.Client, endpoint: Endpoint, payload: dict[str, Any], cancel: Cancel
) -> httpx.Response:
    for attempt in range(CHAT_ATTEMPTS - 1):
        try:
            response = _post(http, endpoint, payload, cancel)
        except httpx.TransportError:
            cancel.wait(_backoff_seconds(attempt))
            continue

        if not _retryable(response):
            return response

        response.close()
        cancel.wait(_backoff_seconds(attempt))

    return _post(http, endpoint, payload, cancel)


def stream(
    endpoint: Endpoint,
    payload: dict[str, Any],
    *,
    cancel: Cancel,
    on_text: Callable[[str], None],
    on_reasoning: Callable[[str], None] = ignore,
) -> StreamResult:
    streamed = False

    def forward(handler: Callable[[str], None]) -> Callable[[str], None]:
        def send(text: str) -> None:
            nonlocal streamed
            streamed = True
            handler(text)

        return send

    for attempt in range(CHAT_ATTEMPTS):
        try:
            return _stream_once(endpoint, payload, cancel, forward(on_text), forward(on_reasoning))
        except httpx.TransportError as exc:
            if cancel.is_set():
                raise Cancelled from None

            if streamed or attempt == CHAT_ATTEMPTS - 1:
                raise endpoint.error(
                    f"Lost the connection to {endpoint.name}: {exc}. Send a message to continue."
                ) from exc

            cancel.wait(_backoff_seconds(attempt))

    raise endpoint.error(f"{endpoint.name} chat retries ran out.")


def _stream_once(
    endpoint: Endpoint,
    payload: dict[str, Any],
    cancel: Cancel,
    on_text: Callable[[str], None],
    on_reasoning: Callable[[str], None],
) -> StreamResult:
    with httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS, read=CHAT_READ_TIMEOUT_SECONDS)) as http:
        response = _send_with_retries(http, endpoint, payload, cancel)
        with cancel.hook(response.close):
            if response.status_code >= httpx.codes.BAD_REQUEST:
                detail = response.read().decode("utf-8", "replace")[:ERROR_DETAIL_CHARS]
                raise endpoint.error(f"{endpoint.name} chat failed ({response.status_code}): {detail}")

            try:
                return _read_stream(endpoint, response, on_text, on_reasoning)
            except httpx.HTTPError:
                if cancel.is_set():
                    raise Cancelled from None
                raise


def complete(endpoint: Endpoint, payload: dict[str, Any], read_timeout: float) -> tuple[str, Usage | None]:
    with httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS, read=read_timeout)) as http:
        response = http.post(endpoint.url + CHAT_PATH, json=payload, headers=endpoint.headers)

    if response.status_code >= httpx.codes.BAD_REQUEST:
        raise endpoint.error(
            f"{endpoint.name} chat failed ({response.status_code}): {response.text[:ERROR_DETAIL_CHARS]}"
        )

    body = response.json()
    content = body["choices"][0]["message"].get("content")
    if not content:
        raise endpoint.error(f"{endpoint.name} returned an empty reply from {payload['model']}.")
    return content.strip(), endpoint.usage_of(body)


def _chunks(endpoint: Endpoint, response: httpx.Response) -> Iterator[dict[str, Any]]:
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
            raise endpoint.error(
                f"{endpoint.name} sent a malformed stream chunk: {data[:ERROR_DETAIL_CHARS]}"
            ) from None


def _merge_tool_call(calls: dict[tuple[int, int], dict[str, Any]], choice: int, part: dict[str, Any]) -> None:
    key = (choice, part.get("index") or 0)
    call = calls.setdefault(key, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    if part.get("id"):
        call["id"] = part["id"]

    function = part.get("function") or {}
    call["function"]["name"] += function.get("name") or ""
    call["function"]["arguments"] += function.get("arguments") or ""


def _reasoning_of(delta: dict[str, Any]) -> str:
    return next((delta[key] for key in REASONING_KEYS if delta.get(key)), "")


def _read_stream(
    endpoint: Endpoint,
    response: httpx.Response,
    on_text: Callable[[str], None],
    on_reasoning: Callable[[str], None],
) -> StreamResult:
    result = StreamResult()
    calls: dict[tuple[int, int], dict[str, Any]] = {}
    for chunk in _chunks(endpoint, response):
        result.usage = endpoint.usage_of(chunk) or result.usage
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            thought = _reasoning_of(delta)
            if thought:
                result.reasoning += thought
                on_reasoning(thought)

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
