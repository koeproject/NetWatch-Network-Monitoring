"""1.1, 1.7, 1.8 — domain rules, auth primitives, live stream filtering."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.auth.passwords import hash_password, verify_password
from app.auth.sessions import SessionSigner
from app.bus.memory import MemoryBus
from app.cache import MemoryCache, token_scope
from app.domain.enums import Severity
from app.domain.models import MetricPoint, Problem, Tenant
from app.services.inventory import InventoryService
from app.services.stream import HEARTBEAT, StreamService
from tests.fakes import FakeEngine


# -- 1.1 domain ---------------------------------------------------------------
def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MetricPoint("d", "cpu", datetime(2026, 10, 9, 10, 0), 1.0)
    with pytest.raises(ValueError, match="timezone-aware"):
        Problem("P1", "d", Severity.MAJOR, "t", datetime(2026, 10, 9, 10, 0))


def test_severity_is_ordered() -> None:
    assert Severity.CRITICAL > Severity.MAJOR > Severity.MINOR > Severity.WARNING > Severity.INFO


# -- 1.7 auth -----------------------------------------------------------------
def test_password_hash_round_trip() -> None:
    stored = hash_password("correct horse battery")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")
    assert hash_password("same") != hash_password("same")  # salted


def test_session_sign_verify_expire() -> None:
    signer = SessionSigner("k" * 32, ttl_seconds=60)
    token = signer.issue("alice", "hq", now=1000)

    session = signer.verify(token, now=1030)
    assert session is not None and (session.username, session.tenant_id) == ("alice", "hq")
    assert signer.verify(token, now=1061) is None  # expired
    assert SessionSigner("j" * 32, 60).verify(token, now=1030) is None  # other key
    assert signer.verify("no-dot", now=1030) is None


def test_session_secret_must_be_long() -> None:
    with pytest.raises(ValueError):
        SessionSigner("short", 60)


def test_cache_key_never_contains_the_token() -> None:
    assert "token-hq" not in token_scope("token-hq")
    assert token_scope("token-hq") != token_scope("token-branch")


# -- 1.8 stream ---------------------------------------------------------------
@pytest.mark.anyio
async def test_stream_only_delivers_the_tenants_devices() -> None:
    bus = MemoryBus()
    inventory = InventoryService(FakeEngine(), MemoryCache(), ttl_seconds=60)
    stream = StreamService(bus, inventory, heartbeat_seconds=5)
    hq = Tenant("hq", "HQ", "token-hq")

    received: list[dict] = []

    async def listen() -> None:
        async for message in stream.events(hq):
            received.append(message)
            if len(received) == 2:
                return

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.05)  # let it subscribe
    await bus.publish({"type": "metrics", "device_ref": "branch-sw-01"})  # not HQ's
    await bus.publish({"type": "problem", "device_ref": "core-sw-01"})
    await bus.publish({"type": "metrics", "device_ref": "Zabbix server"})
    await asyncio.wait_for(task, timeout=2)

    assert [m["device_ref"] for m in received] == ["core-sw-01", "Zabbix server"]


@pytest.mark.anyio
async def test_stream_sends_heartbeat_when_idle() -> None:
    inventory = InventoryService(FakeEngine(), MemoryCache(), ttl_seconds=60)
    stream = StreamService(MemoryBus(), inventory, heartbeat_seconds=0.05)
    events = stream.events(Tenant("hq", "HQ", "token-hq"))

    assert await asyncio.wait_for(anext(events), timeout=1) is HEARTBEAT
    await events.aclose()


@pytest.mark.anyio
async def test_bus_unsubscribes_on_exit() -> None:
    bus = MemoryBus()
    async with bus.subscribe():
        assert len(bus._subscribers) == 1
    assert len(bus._subscribers) == 0
