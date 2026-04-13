"""
Mark II Studio — SSE Event Bus
In-process async event bus for streaming session events to clients.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import AsyncGenerator
from uuid import UUID

from app.schemas.events import BaseEvent

logger = logging.getLogger(__name__)


class EventBus:
    """
    Per-session async event bus.

    Each session has a list of subscriber queues.
    Publishing an event pushes it to all active subscribers.
    SSE endpoints consume events from their queue.
    """

    def __init__(self) -> None:
        self._subscribers: dict[UUID, list[asyncio.Queue[BaseEvent | None]]] = defaultdict(list)

    def subscribe(self, session_id: UUID) -> asyncio.Queue[BaseEvent | None]:
        """Create a new subscriber queue for a session."""
        queue: asyncio.Queue[BaseEvent | None] = asyncio.Queue(maxsize=256)
        self._subscribers[session_id].append(queue)
        logger.info("SSE subscriber added for session %s (total=%d)", session_id, len(self._subscribers[session_id]))
        return queue

    def unsubscribe(self, session_id: UUID, queue: asyncio.Queue[BaseEvent | None]) -> None:
        """Remove a subscriber queue."""
        subs = self._subscribers.get(session_id, [])
        if queue in subs:
            subs.remove(queue)
        if not subs:
            self._subscribers.pop(session_id, None)
        logger.info("SSE subscriber removed for session %s", session_id)

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all subscribers of its session."""
        session_id = event.session_id
        subs = self._subscribers.get(session_id, [])
        dead: list[asyncio.Queue] = []
        for queue in subs:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("SSE queue full for session %s, dropping subscriber", session_id)
                dead.append(queue)
        for q in dead:
            self.unsubscribe(session_id, q)

    async def stream(self, session_id: UUID) -> AsyncGenerator[str, None]:
        """
        Yield SSE-formatted strings for a session.
        Used by the SSE endpoint handler.
        """
        queue = self.subscribe(session_id)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break  # Sentinel — stream closed
                yield _format_sse(event)
        finally:
            self.unsubscribe(session_id, queue)

    async def close_session(self, session_id: UUID) -> None:
        """Send sentinel to all subscribers, closing their streams."""
        subs = self._subscribers.get(session_id, [])
        for queue in subs:
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.pop(session_id, None)


def _format_sse(event: BaseEvent) -> str:
    """Format an event as an SSE message string."""
    payload = event.model_dump(mode="json")
    data_json = json.dumps(payload, default=str)
    return f"event: {event.event_type}\ndata: {data_json}\n\n"


# Singleton event bus instance
event_bus = EventBus()
