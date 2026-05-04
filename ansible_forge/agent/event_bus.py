"""In-process event bus for decoupling agent execution from SSE delivery.

The agent writes events to a per-session queue.  Multiple SSE readers can
attach, detach, and re-attach without affecting the agent's progress.
Events are also stored in ``SessionStore`` so they survive reconnections.

Subscriber queues are unbounded — infrastructure playbook runs can last
hours or days, generating thousands of events.  A dead-subscriber reaper
evicts any queue that grows past ``_DEAD_SUBSCRIBER_THRESHOLD``, which
only happens when the SSE connection has silently died without unsubscribing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_EVENT_BUFFER_SIZE = 5_000
_DEAD_SUBSCRIBER_THRESHOLD = 10_000

_TRANSIENT_EVENTS = frozenset({"thinking_delta", "message_delta", "progress", "live_log"})


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

    @property
    def min_seq(self) -> int:
        if self._buffer:
            return self._buffer[0]["seq"]
        return self._seq

    def publish(self, event_type: str, data: dict[str, Any]) -> int:
        self._seq += 1
        wrapped = {
            "seq": self._seq,
            "event": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        self._buffer.append(wrapped)

        dead: list[asyncio.Queue[dict[str, Any] | None]] = []
        for q in self._subscribers:
            if q.qsize() >= _DEAD_SUBSCRIBER_THRESHOLD:
                dead.append(q)
                continue
            q.put_nowait(wrapped)

        if dead:
            for q in dead:
                logger.warning(
                    "dead_subscriber_reaped",
                    session_id=self.session_id,
                    queue_size=q.qsize(),
                )
                with contextlib.suppress(ValueError):
                    self._subscribers.remove(q)

        return self._seq

    def mark_running(self) -> int:
        """Mark bus as running. Returns a generation token to pass to mark_done."""
        self._run_gen += 1
        self._running = True
        self._done = False
        return self._run_gen

    def is_current_run(self, gen: int) -> bool:
        """True if *gen* matches the latest ``mark_running`` generation."""
        return gen == 0 or gen == self._run_gen

    def mark_done(self, gen: int = 0) -> None:
        """Mark bus as done. Only the latest generation's task can actually mark done."""
        if gen and gen != self._run_gen:
            return
        self._running = False
        self._done = True
        for q in self._subscribers:
            q.put_nowait(None)

    def subscribe(self, from_seq: int = 0) -> asyncio.Queue[dict[str, Any] | None]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        if from_seq > 0:
            for event in self._buffer:
                if event["seq"] > from_seq:
                    q.put_nowait(event)
        self._subscribers.append(q)
        if self._done:
            q.put_nowait(None)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(q)

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
