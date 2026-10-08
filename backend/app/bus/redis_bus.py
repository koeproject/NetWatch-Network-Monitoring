"""BusPort over Redis pub/sub — reaches every uvicorn worker.

The worker that receives a push publishes once; every worker holding an SSE
connection is subscribed and forwards to its own browsers. Redis is ours only
(CLAUDE.md §2); the engine never touches it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from redis.asyncio import Redis

CHANNEL = "acme:live"


class RedisBus:
    def __init__(self, url: str) -> None:
        self._redis = Redis.from_url(url)

    async def publish(self, message: dict[str, Any]) -> None:
        await self._redis.publish(CHANNEL, json.dumps(message))

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(CHANNEL)

        async def messages() -> AsyncIterator[dict[str, Any]]:
            async for raw in pubsub.listen():
                if raw.get("type") == "message":
                    yield json.loads(raw["data"])

        try:
            yield messages()
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.aclose()

    async def close(self) -> None:
        await self._redis.aclose()
