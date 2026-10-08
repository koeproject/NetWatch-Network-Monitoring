"""Cache for engine API responses (CachePort): in-process or Redis.

Only lookups are cached (device lists). Values must be JSON-serialisable so
both implementations behave the same.

Every key that depends on who is asking must include ``token_scope(token)``:
two tenants asking the same question must never share an answer.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from redis.asyncio import Redis


def token_scope(token: str) -> str:
    """Short, non-reversible tag for a token, safe to put in a cache key."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class MemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires, raw = item
        if time.monotonic() >= expires:
            del self._items[key]
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._items[key] = (time.monotonic() + ttl_seconds, json.dumps(value))

    async def close(self) -> None:
        self._items.clear()


class RedisCache:
    PREFIX = "acme:cache:"

    def __init__(self, url: str) -> None:
        self._redis = Redis.from_url(url)

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(self.PREFIX + key)
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self._redis.set(self.PREFIX + key, json.dumps(value), ex=ttl_seconds)

    async def close(self) -> None:
        await self._redis.aclose()
