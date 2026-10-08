"""Portal login (ADR 0008): signed session token in an HttpOnly cookie."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.api.deps import SESSION_COOKIE, ContainerDep, TenantDep

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response, container: ContainerDep) -> dict[str, str]:
    token = await container.auth.login(body.username, body.password)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=container.settings.session_ttl_hours * 3600,
        httponly=True,  # page scripts cannot read it
        samesite="strict",
        secure=container.settings.cookie_secure,
    )
    # Also returned for scripts and curl, which send it as a Bearer header.
    return {"token": token}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me")
async def me(tenant: TenantDep) -> dict[str, str]:
    return {"tenant_id": tenant.id, "tenant_name": tenant.name}
