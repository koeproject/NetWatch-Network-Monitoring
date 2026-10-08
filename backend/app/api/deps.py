"""Shared FastAPI dependencies: the container, and the caller's tenant."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.container import Container
from app.domain.models import Tenant

SESSION_COOKIE = "acme_session"


def get_container(request: Request) -> Container:
    return request.app.state.container


def session_token(request: Request) -> str | None:
    """Cookie for the browser (EventSource cannot set headers), Bearer for scripts."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header.removeprefix("Bearer ").strip()
    return request.cookies.get(SESSION_COOKIE)


async def current_tenant(
    request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> Tenant:
    token = session_token(request)
    tenant = await container.auth.tenant_for(token) if token else None
    if tenant is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "not signed in",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return tenant


ContainerDep = Annotated[Container, Depends(get_container)]
TenantDep = Annotated[Tenant, Depends(current_tenant)]
