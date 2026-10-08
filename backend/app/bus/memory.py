"""BusPort inside one process.

Each subscriber gets its own bounded queue. A subscriber that stops reading
(a stalled browser) loses messages instead of growing memory without limit;
the portal re-reads state from the API when it reconnects.

Only reaches subscribers in the same uvicorn worker. With more than one
worker, use bus/redis_bus.py.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

log = logging.getLogger(__name__)


class MemoryBus:
    def __init__(self, queue_size: int = 1000) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    async def publish(self, message: dict[str, Any]) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("bus subscriber is full; message dropped")

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._queue_size)
        self._subscribers.add(queue)

        async def messages() -> AsyncIterator[dict[str, Any]]:
            while True:
                yield await queue.get()

        try:
            yield messages()
        finally:
            self._subscribers.discard(queue)

    async def close(self) -> None:
        self._subscribers.clear()
