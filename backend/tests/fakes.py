"""Test doubles for the ports, and a ready-made app around them."""

from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from app.config import Settings
from app.container import Container, build_container
from app.domain.enums import DeviceKind, DeviceStatus
from app.domain.models import Device
from app.domain.ports import DeviceNotFound, EngineUnavailable
from app.store.sqlite_store import SqliteStore
from app.crypto import TokenCipher

PUSH_TOKEN = "push-token-for-tests"

# What each tenant's read token is allowed to see — like host-group permissions.
DEVICES = {
    "token-hq": [
        Device("Zabbix server", "Lab server", DeviceKind.SERVER, "HQ", DeviceStatus.UP),
        Device("core-sw-01", "Core 01", DeviceKind.CORE_SWITCH, "HQ", DeviceStatus.UP),
    ],
    "token-branch": [
        Device("branch-sw-01", "Branch 01", DeviceKind.ACCESS_SWITCH, "BR", DeviceStatus.DOWN),
    ],
}


class FakeEngine:
    def __init__(self) -> None:
        self.calls = 0
        self.down = False

    async def list_devices(self, token: str) -> list[Device]:
        self.calls += 1
        if self.down:
            raise EngineUnavailable("connection refused")
        return list(DEVICES.get(token, []))

    async def get_device(self, ref: str, token: str) -> Device:
        for d in await self.list_devices(token):
            if d.ref == ref:
                return d
        raise DeviceNotFound(ref)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        store_url=f"sqlite:///{tmp_path / 'store.db'}",
        push_token=PUSH_TOKEN,
        token_key=Fernet.generate_key().decode(),
        session_secret="s" * 48,
        cookie_secure=False,
        redis_url=None,
        frontend_dist=str(tmp_path / "no-portal"),
    )


def make_container(tmp_path: Path, engine: FakeEngine) -> Container:
    settings = make_settings(tmp_path)
    store = SqliteStore(tmp_path / "store.db", TokenCipher(settings.token_key))
    return build_container(settings, engine=engine, store=store)
