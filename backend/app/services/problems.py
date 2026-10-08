"""Problem lists — from our store, scoped to the tenant's devices."""

from __future__ import annotations

from app.domain.models import Problem, Tenant
from app.domain.ports import StorePort
from app.services.inventory import InventoryService


class ProblemsService:
    def __init__(self, store: StorePort, inventory: InventoryService) -> None:
        self._store = store
        self._inventory = inventory

    async def list(
        self,
        tenant: Tenant,
        *,
        device_ref: str | None = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> list[Problem]:
        if device_ref is not None:
            await self._inventory.device(tenant, device_ref)  # scope check
            refs = {device_ref}
        else:
            refs = await self._inventory.device_refs(tenant)
        return await self._store.problems(refs, active_only=active_only, limit=limit)
