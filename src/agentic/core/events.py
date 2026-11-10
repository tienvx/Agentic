"""In-process event bus.

Stage and agent progress is emitted as events; the CLI renders them and the
HTTP service re-publishes them as A2A ``TaskStatusUpdateEvent`` / SSE frames.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

Listener = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    kind: str
    stage: str = ""
    agent: str = ""
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            object.__setattr__(self, "timestamp", datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "stage": self.stage,
            "agent": self.agent,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class EventBus:
    """Fan-out bus with a bounded replay buffer for late subscribers."""

    def __init__(self, replay: int = 512) -> None:
        self._queues: list[asyncio.Queue[Event]] = []
        self._listeners: list[Listener] = []
        self._replay: list[Event] = []
        self._replay_limit = replay

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        for event in self._replay:
            queue.put_nowait(event)
        self._queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        if queue in self._queues:
            self._queues.remove(queue)

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def emit(self, event: Event) -> None:
        self._replay.append(event)
        if len(self._replay) > self._replay_limit:
            self._replay.pop(0)
        for queue in list(self._queues):
            queue.put_nowait(event)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - a bad listener must not break a run
                pass

    async def stream(self) -> AsyncIterator[Event]:
        queue = self.subscribe()
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(queue)
