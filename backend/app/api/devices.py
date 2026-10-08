"""Devices, their metrics and latest values.

The device list comes from the engine port (cached); every number comes from
our store. Nothing here reads past values from the engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import ContainerDep, TenantDep
from app.services.views import device_view, point_view

router = APIRouter(prefix="/api", tags=["devices"])


def _aware(value: datetime | None, name: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{name}' needs a timezone, e.g. 2026-10-09T10:00:00+07:00",
        )
    return value


@router.get("/devices")
async def list_devices(tenant: TenantDep, container: ContainerDep) -> list[dict[str, Any]]:
    return [device_view(d) for d in await container.inventory.devices(tenant)]


@router.get("/devices/{ref}")
async def get_device(ref: str, tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return device_view(await container.inventory.device(tenant, ref))


@router.get("/devices/{ref}/latest")
async def device_latest(ref: str, tenant: TenantDep, container: ContainerDep) -> list[dict[str, Any]]:
    return [point_view(p) for p in await container.metrics.latest(tenant, ref)]


@router.get("/devices/{ref}/metrics")
async def device_metrics(
    ref: str,
    tenant: TenantDep,
    container: ContainerDep,
    metric: str | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    step: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    try:
        used_step, series = await container.metrics.series(
            tenant,
            ref,
            metric=metric,
            start=_aware(start, "from"),
            end=_aware(end, "to"),
            step_seconds=step,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {
        "device_ref": ref,
        "step": used_step,
        "series": {
            name: [{"ts": p.ts.isoformat(), "value": p.value} for p in points]
            for name, points in series.items()
        },
    }


@router.get("/latest")
async def latest(tenant: TenantDep, container: ContainerDep) -> list[dict[str, Any]]:
    """Every latest value this tenant may see — the overview tiles."""
    return [
        {"device_ref": p.device_ref, **point_view(p)}
        for p in await container.metrics.latest(tenant)
    ]
