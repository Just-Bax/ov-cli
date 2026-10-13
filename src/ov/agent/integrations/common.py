from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Self

import httpx

from ov.core.paths import agent_dir, write_atomic

ERROR_BODY_CHARS = 200


class TimedCache:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        cached = self._entries.get(key)
        fresh = cached is not None and time.time() - cached[0] < self._ttl_seconds
        return cached[1] if fresh else None

    def put(self, key: Any, value: Any) -> None:
        self._entries[key] = (time.time(), value)

    def clear(self) -> None:
        self._entries.clear()


class Service:
    def __init__(self, name: str, state_name: str, marker: str, error: type[Exception]) -> None:
        self.name = name
        self.error = error
        self._state_name = state_name
        self._marker = marker
        self._lock = threading.Lock()

    def state_file(self) -> Path:
        return agent_dir() / self._state_name

    def load_state(self) -> dict[str, Any]:
        path = self.state_file()
        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise self.error(f"Cannot read the {self.name} settings in {path}: {exc}") from None
        if isinstance(data, dict):
            return data

        raise self.error(f"The {self.name} settings in {path} are not a JSON object.")

    def save_state(self, state: dict[str, Any]) -> None:
        with self._lock:
            write_atomic(self.state_file(), json.dumps(state, indent=2))

    def stored(self, state: dict[str, Any], key: str) -> Any:
        if key not in state:
            raise self.error(
                f"The {self.name} settings have no {key}. Reconnect {self.name} in Settings > Integrations."
            )
        return state[key]

    def field(self, data: dict[str, Any], key: str) -> Any:
        if key not in data:
            raise self.error(f"{self.name} returned a response without {key}.")
        return data[key]

    def permissions(self, areas: Iterable[str]) -> dict[str, bool]:
        state = self.load_state()
        if self._marker not in state:
            return dict.fromkeys(areas, False)

        stored = self.stored(state, "permissions")
        return {area: bool(stored[area]) for area in areas}

    def details(self, state: dict[str, Any], on: bool, private: tuple[str, ...]) -> dict[str, Any]:
        return {key: self.stored(state, key) for key in private} if on else dict.fromkeys(private)


class HttpClient:
    def __init__(
        self,
        service: Service,
        base_url: str,
        headers: dict[str, str],
        *,
        timeout: float,
        transport: httpx.BaseTransport | None,
        rate_limit_wait: Callable[[httpx.Response], float],
    ) -> None:
        self._service = service
        self._rate_limit_wait = rate_limit_wait
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=timeout, transport=transport)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: Any) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise self._service.error(f"Could not reach {self._service.name}: {exc}") from None

    def send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._request(method, path, **kwargs)
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            time.sleep(self._rate_limit_wait(response))
            response = self._request(method, path, **kwargs)
        return response


def payload(response: httpx.Response) -> Any:
    return response.json() if response.content else {}


def explain(
    service: Service,
    response: httpx.Response,
    messages: dict[int, str],
    forbidden: str,
    errors_in: Callable[[Any], str],
) -> str:
    code = response.status_code
    if code in messages:
        return messages[code]
    if code == httpx.codes.FORBIDDEN:
        return forbidden

    try:
        detail = errors_in(response.json())
    except ValueError:
        detail = ""
    return f"{service.name} returned {code}: {detail or response.text[:ERROR_BODY_CHARS]}"
