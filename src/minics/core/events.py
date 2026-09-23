"""In-process event bus.

Anything that takes a noticeable amount of time should announce itself.  The bus
is a tiny thread-safe pub/sub hub: producers call :meth:`EventBus.publish` and
consumers (usually the SSE endpoint feeding the UI) subscribe to a queue.

Events are also kept in a bounded ring buffer so a reconnecting client can catch
up on what it missed.
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

#: Levels, ordered by increasing severity.
LEVELS = ("debug", "info", "success", "warning", "error")


@dataclass
class Event:
    """A single thing that happened."""

    type: str
    message: str = ""
    level: str = "info"
    progress: float | None = None
    source: str = "app"
    data: dict[str, Any] = field(default_factory=dict)
    id: int = 0
    ts: float = field(default_factory=time.time)
    job_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "message": self.message,
            "level": self.level,
            "progress": self.progress,
            "source": self.source,
            "data": self.data,
            "ts": self.ts,
            "job_id": self.job_id,
        }


class EventBus:
    """Thread-safe publish/subscribe with replayable history."""

    def __init__(self, *, history: int = 500, queue_size: int = 1000) -> None:
        self._subscribers: set[queue.Queue[Event]] = set()
        self._lock = threading.Lock()
        self._history: deque[Event] = deque(maxlen=history)
        self._queue_size = queue_size
        self._counter = itertools.count(1)

    # -- pub/sub ---------------------------------------------------------
    def subscribe(self) -> queue.Queue[Event]:
        q: queue.Queue[Event] = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[Event]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: Event | None = None, **kwargs: Any) -> Event:
        """Publish an :class:`Event` (or build one from keyword arguments)."""
        if event is None:
            event = Event(**kwargs)
        event.id = next(self._counter)
        event.ts = event.ts or time.time()
        with self._lock:
            subscribers = list(self._subscribers)
            self._history.append(event)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:  # pragma: no cover - slow consumer
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except queue.Empty:
                    pass
        return event

    # -- history / streaming --------------------------------------------
    def history(self, limit: int | None = None, *, after_id: int = 0) -> list[Event]:
        with self._lock:
            events = [e for e in self._history if e.id > after_id]
        return events[-limit:] if limit else events

    def stream(
        self,
        *,
        after_id: int = 0,
        timeout: float = 15.0,
        stop: threading.Event | None = None,
    ) -> Iterator[Event | None]:
        """Yield events as they arrive; ``None`` acts as a keep-alive ping."""
        q = self.subscribe()
        try:
            yield from self.history(after_id=after_id)
            while not (stop and stop.is_set()):
                try:
                    yield q.get(timeout=timeout)
                except queue.Empty:
                    yield None
        finally:
            self.unsubscribe(q)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
