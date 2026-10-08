"""Settings, read from the environment or backend/.env.

Names are ENGINE_*, never ZABBIX_* (CLAUDE.md §4): the rest of the backend
must not know which engine it is talking to.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base URL of the engine's web container, without /api_jsonrpc.php.
    engine_url: str = "http://127.0.0.1:8080"

    # Provisioning/admin token ONLY (decision #4). The read path uses a
    # per-tenant token and never this one, so the running backend does not
    # need it; provisioning scripts and the smoke test do. client.py does not
    # import this module — callers pass the token in explicitly.
    engine_token: str | None = None

    # Our store. "sqlite:///path" for tests and the demo,
    # "postgresql://acme_app:...@db:5432/acme" for the appliance.
    store_url: str = "sqlite:///./acme-store.db"
    # Raw metric points older than this are dropped (Postgres only, ADR 0007).
    store_retention_days: int = 30

    # Unset = in-process bus and cache (one uvicorn worker only).
    redis_url: str | None = None

    # Bearer token the push (Connector) must send to /hooks/*.
    push_token: str
    # Fernet key that encrypts tenant read tokens at rest (app/crypto.py).
    token_key: str
    # HMAC key that signs portal session tokens (ADR 0008).
    session_secret: str
    session_ttl_hours: int = 12
    # Mark the session cookie Secure. False only for plain-http local dev.
    cookie_secure: bool = True

    # How long a tenant's device list from the engine is cached.
    inventory_ttl_seconds: int = 60

    # Built portal (Phase 3). Served by main.py when the folder exists.
    frontend_dist: str = "../frontend/dist"


def get_settings() -> Settings:
    return Settings()
