"""Graphs and latest values — from our store only (CLAUDE.md §3, ADR 0005).

No call in this module reaches the engine except the inventory check, which
is a cached device-list lookup, never a history read.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.domain.models import MetricPoint, Tenant
from app.domain.ports import StorePort
from app.services.inventory import InventoryService

# A graph never needs more points than it has pixels; cap what one request
# can pull out of the store.
MAX_POINTS = 2000
DEFAULT_POINTS = 300
MIN_STEP_SECONDS = 60


def choose_step(start: datetime, end: datetime, requested: int | None) -> int:
    span = (end - start).total_seconds()
    floor = max(MIN_STEP_SECONDS, math.ceil(span / MAX_POINTS))
    if requested is None:
        return max(floor, math.ceil(span / DEFAULT_POINTS))
    return max(floor, requested)


class MetricsService:
    def __init__(self, store: StorePort, inventory: InventoryService) -> None:
        self._store = store
        self._inventory = inventory

    async def latest(self, tenant: Tenant, device_ref: str | None = None) -> list[MetricPoint]:
        if device_ref is not None:
            await self._inventory.device(tenant, device_ref)  # scope check
            return await self._store.latest([device_ref])
        return await self._store.latest(await self._inventory.device_refs(tenant))

    async def series(
        self,
        tenant: Tenant,
        device_ref: str,
        *,
        metric: str | None,
        start: datetime | None,
        end: datetime | None,
        step_seconds: int | None,
    ) -> tuple[int, dict[str, list[MetricPoint]]]:
        """Returns (step actually used, {metric: points}).

        No ``metric`` = every metric this device has a latest value for.
        """
        await self._inventory.device(tenant, device_ref)  # scope check

        end = end or datetime.now().astimezone()
        start = start or end - timedelta(hours=1)
        if start >= end:
            raise ValueError("'from' must be before 'to'")
        step = choose_step(start, end, step_seconds)

        if metric is not None:
            names = [metric]
        else:
            names = sorted({p.metric for p in await self._store.latest([device_ref])})

        return step, {
            name: await self._store.series(device_ref, name, start, end, step) for name in names
        }
