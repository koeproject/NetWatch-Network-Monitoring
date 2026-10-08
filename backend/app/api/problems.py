"""Problems — from our store, scoped to the caller's tenant."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, TenantDep
from app.services.views import problem_view

router = APIRouter(prefix="/api", tags=["problems"])


@router.get("/problems")
async def list_problems(
    tenant: TenantDep,
    container: ContainerDep,
    device: str | None = None,
    active: bool = True,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[dict[str, Any]]:
    problems = await container.problems.list(
        tenant, device_ref=device, active_only=active, limit=limit
    )
    return [problem_view(p) for p in problems]
