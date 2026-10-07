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
    # per-tenant token and never this one. client.py does not import this
    # module — callers pass the token in explicitly.
    engine_token: str


def get_settings() -> Settings:
    return Settings()
