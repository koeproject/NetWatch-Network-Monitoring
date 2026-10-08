"""Live updates for one portal connection, filtered to its tenant.

The bus carries every tenant's messages; this is where a connection only
gets its own. The tenant's device set is refreshed periodically so a device
added by provisioning starts streaming without a reconnect.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from app.domain.models import Tenant
from app.domain.ports import BusPort
from app.services.inventory import InventoryService

HEARTBEAT = {"type": "heartbeat"}


class StreamService:
    def __init__(
        self,
        bus: BusPort,
        inventory: InventoryService,
        *,
        heartbeat_seconds: float = 15.0,
        refresh_seconds: float = 60.0,
    ) -> None:
        self._bus = bus
        self._inventory = inventory
        self._heartbeat = heartbeat_seconds
        self._refresh = refresh_seconds

    async def events(self, tenant: Tenant) -> AsyncIterator[dict[str, Any]]:
        """Messages for this tenant, plus a heartbeat when idle (keeps proxies
        from closing the connection and lets the browser notice a dead one)."""
        refs = await self._inventory.device_refs(tenant)
        refreshed = time.monotonic()

        async with self._bus.subscribe() as messages:
            pending: asyncio.Task[dict[str, Any]] | None = None
            try:
                while True:
                    if pending is None:
                        pending = asyncio.ensure_future(anext(messages))
                    done, _ = await asyncio.wait({pending}, timeout=self._heartbeat)
                    if not done:
                        yield HEARTBEAT
                        continue
                    message, pending = pending.result(), None

                    if time.monotonic() - refreshed > self._refresh:
                        refs = await self._inventory.device_refs(tenant)
                        refreshed = time.monotonic()
                    if message.get("device_ref") in refs:
                        yield message
            finally:
                if pending is not None:
                    pending.cancel()
