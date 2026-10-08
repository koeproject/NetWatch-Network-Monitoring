"""Devices a tenant may see, looked up through the engine port and cached.

Every lookup uses the tenant's own read token (ADR 0004), so the engine's
permissions decide the device list. That list is then the filter for
everything we read from our own store — the engine's permissions do not
reach our store, so this filter must be applied on every store read.
"""

from __future__ import annotations

from app.cache import token_scope
from app.domain.models import Device, Tenant
from app.domain.ports import CachePort, DeviceNotFound, MonitoringEnginePort
from app.services.views import device_from_view, device_view


class InventoryService:
    def __init__(self, engine: MonitoringEnginePort, cache: CachePort, ttl_seconds: int) -> None:
        self._engine = engine
        self._cache = cache
        self._ttl = ttl_seconds

    async def devices(self, tenant: Tenant) -> list[Device]:
        key = f"devices:{token_scope(tenant.engine_token)}"
        cached = await self._cache.get(key)
        if cached is not None:
            return [device_from_view(v) for v in cached]

        devices = await self._engine.list_devices(tenant.engine_token)
        await self._cache.set(key, [device_view(d) for d in devices], self._ttl)
        return devices

    async def device_refs(self, tenant: Tenant) -> set[str]:
        return {d.ref for d in await self.devices(tenant)}

    async def device(self, tenant: Tenant, ref: str) -> Device:
        """The device, if this tenant may see it. Raises DeviceNotFound otherwise
        — the same answer for "does not exist" and "not yours"."""
        for d in await self.devices(tenant):
            if d.ref == ref:
                return d
        raise DeviceNotFound(ref)
