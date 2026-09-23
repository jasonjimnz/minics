"""Server-Sent Events helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from flask import Response, stream_with_context

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_event(data: Any, *, event: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {payload}\n\n"


def sse_response(events: Iterable[dict[str, Any]]) -> Response:
    """Turn an iterable of event dicts into an SSE ``text/event-stream``."""

    def generate() -> Iterator[str]:
        try:
            for item in events:
                if item is None:
                    yield ": keep-alive\n\n"
                    continue
                event_name = item.get("type") if isinstance(item, dict) else None
                yield format_event(item, event=event_name)
        except GeneratorExit:  # pragma: no cover - client disconnected
            return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers=SSE_HEADERS,
    )
