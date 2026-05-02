"""In-process event bus for decoupling agent execution from SSE delivery.

The agent writes events to a per-session queue.  Multiple SSE readers can
attach, detach, and re-attach without affecting the agent's progress.
Events are also stored in ``SessionStore`` so they survive reconnections.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_EVENT_BUFFER_SIZE = 500


class SessionEventBus:
    """Buffered event bus for a single session."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._buffer: deque[dict[str, Any]] = deque(maxlen=_EVENT_BUFFER_SIZE)
        self._seq = 0
        self._subscribers: list[asyncio.Queue[dict[str, Any] | None]] = []
        self._done = False
        self._running = False
        self._run_gen = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_done(self) -> bool:
        return self._done

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        self._seq += 1
        wrapped = {
            "seq": self._seq,
            "event": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        self._buffer.append(wrapped)
        for q in self._subscribers:
            try:
                q.put_nowait(wrapped)
            except asyncio.QueueFull:
                pass

    def mark_running(self) -> int:
        """Mark bus as running. Returns a generation token to pass to mark_done."""
        self._run_gen += 1
        self._running = True
        self._done = False
        return self._run_gen

    def mark_done(self, gen: int = 0) -> None:
        """Mark bus as done. Only the latest generation's task can actually mark done."""
        if gen and gen != self._run_gen:
            return
        self._running = False
        self._done = True
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    def subscribe(self, from_seq: int = 0) -> asyncio.Queue[dict[str, Any] | None]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=200)
        if from_seq > 0:
            for event in self._buffer:
                if event["seq"] > from_seq:
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        break
        self._subscribers.append(q)
        if self._done:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def get_events_since(self, seq: int) -> list[dict[str, Any]]:
        return [e for e in self._buffer if e["seq"] > seq]


class EventBusRegistry:
    """Global registry of per-session event buses."""

    _instance: EventBusRegistry | None = None

    def __init__(self) -> None:
        self._buses: dict[str, SessionEventBus] = {}

    @classmethod
    def get_instance(cls) -> EventBusRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_or_create(self, session_id: str) -> SessionEventBus:
        if session_id not in self._buses:
            self._buses[session_id] = SessionEventBus(session_id)
        return self._buses[session_id]

    def get(self, session_id: str) -> SessionEventBus | None:
        return self._buses.get(session_id)

    def cleanup(self, session_id: str) -> None:
        self._buses.pop(session_id, None)
