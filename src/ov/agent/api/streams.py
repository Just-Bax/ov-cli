from __future__ import annotations

import json
import queue
from collections.abc import Callable
from typing import Any

from ov.agent.api.handler import Handler, HttpError
from ov.agent.api.screen import Screen
from ov.agent.engine.run import STREAM_END

PING_SECONDS = 15
SSE_PING = "event: ping\ndata: \n\n"


def open_stream(h: Handler) -> None:
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("Cache-Control", "no-cache")
    h.end_headers()


def write_stream(h: Handler, text: str) -> None:
    h.wfile.write(text.encode())
    h.wfile.flush()


def pump(h: Handler, channel: queue.Queue[Any], emit: Callable[[Any], None]) -> None:
    while True:
        try:
            item = channel.get(timeout=PING_SECONDS)
        except queue.Empty:
            write_stream(h, SSE_PING)
            continue
        if item is STREAM_END:
            return
        emit(item)


def stream_screen(h: Handler, screen: Screen) -> None:
    open_stream(h)
    seen = -1
    try:
        with screen.viewing():
            while not screen.closed:
                if not screen.wait(seen, PING_SECONDS):
                    write_stream(h, SSE_PING)
                    continue
                seen = screen.seq

                if screen.frame is not None:
                    write_stream(h, f"data: {json.dumps(screen.frame)}\n\n")

        write_stream(h, f"event: end\ndata: {json.dumps({'error': screen.failure})}\n\n")
    except ConnectionError:
        pass


def push_input(h: Handler, screen: Screen | None) -> dict[str, bool]:
    events = h.json().get("events")
    if not isinstance(events, list):
        raise HttpError(400, "Give a list of events.")
    if screen is None or screen.closed:
        return {"open": False}

    screen.push(events)
    return {"open": True}
