"""Signed, expiring session tokens (ADR 0008).

Format: ``<payload>.<signature>``, both base64url without padding.
payload   = JSON {"u": username, "t": tenant_id, "exp": unix seconds}
signature = HMAC-SHA256(session_secret, payload)

Stateless, so every uvicorn worker can check a token without shared state.
The token is readable by whoever holds it (it is signed, not encrypted), so
it carries no secret — the tenant's read token stays in the store.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Session:
    username: str
    tenant_id: str
    expires_at: int


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SessionSigner:
    def __init__(self, secret: str, ttl_seconds: int) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must be at least 32 characters")
        self._key = secret.encode()
        self._ttl = ttl_seconds

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())

    def issue(self, username: str, tenant_id: str, *, now: float | None = None) -> str:
        expires = int((now if now is not None else time.time()) + self._ttl)
        payload = _b64(json.dumps({"u": username, "t": tenant_id, "exp": expires}).encode())
        return f"{payload}.{self._sign(payload)}"

    def verify(self, token: str, *, now: float | None = None) -> Session | None:
        payload, sep, signature = token.partition(".")
        if not sep or not hmac.compare_digest(signature, self._sign(payload)):
            return None
        try:
            data = json.loads(_unb64(payload))
            session = Session(str(data["u"]), str(data["t"]), int(data["exp"]))
        except (ValueError, KeyError, TypeError):
            return None
        if session.expires_at <= (now if now is not None else time.time()):
            return None
        return session
