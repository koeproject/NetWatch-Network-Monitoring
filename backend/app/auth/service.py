"""Login and "who is this request for" — user -> tenant."""

from __future__ import annotations

from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import SessionSigner
from app.domain.models import Tenant, User
from app.domain.ports import StorePort

# Checked against when the username does not exist, so a wrong username and a
# wrong password take the same time and cannot be told apart.
_DUMMY_HASH = hash_password("timing-equaliser")


class AuthService:
    def __init__(self, store: StorePort, signer: SessionSigner) -> None:
        self._store = store
        self._signer = signer

    async def login(self, username: str, password: str) -> str | None:
        """A session token, or None. Never says which half was wrong."""
        user = await self._store.get_user(username)
        if user is None:
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, user.password_hash):
            return None
        return self._signer.issue(user.username, user.tenant_id)

    async def tenant_for(self, token: str) -> Tenant | None:
        session = self._signer.verify(token)
        if session is None:
            return None
        # Re-read the user: a deleted or moved user loses access at once,
        # not when the token expires.
        user = await self._store.get_user(session.username)
        if user is None or user.tenant_id != session.tenant_id:
            return None
        return await self._store.get_tenant(user.tenant_id)

    async def add_tenant(self, tenant: Tenant) -> None:
        await self._store.save_tenant(tenant)

    async def add_user(self, username: str, tenant_id: str, password: str) -> None:
        if await self._store.get_tenant(tenant_id) is None:
            raise LookupError(f"unknown tenant: {tenant_id}")
        await self._store.save_user(User(username, tenant_id, hash_password(password)))
