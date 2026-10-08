"""The single wiring point (CLAUDE.md §4).

The only module outside backend/app/zabbix/ allowed to name the engine: it
picks the concrete classes and hands them to services as ports. Everything
else receives a Container and never imports an implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.service import AuthService
from app.auth.sessions import SessionSigner
from app.bus.memory import MemoryBus
from app.bus.redis_bus import RedisBus
from app.cache import MemoryCache, RedisCache
from app.config import Settings
from app.crypto import TokenCipher
from app.domain.ports import (
    BusPort,
    CachePort,
    MonitoringEnginePort,
    PushDecoderPort,
    StorePort,
)
from app.services.ingest import IngestService
from app.services.inventory import InventoryService
from app.services.metrics import MetricsService
from app.services.problems import ProblemsService
from app.services.stream import StreamService
from app.store.postgres_store import PostgresStore
from app.store.sqlite_store import SqliteStore
from app.zabbix.adapter import ZabbixAdapter
from app.zabbix.client import ZabbixClient
from app.zabbix.connector_ingest import ConnectorDecoder


@dataclass
class Container:
    settings: Settings
    engine: MonitoringEnginePort
    decoder: PushDecoderPort
    store: StorePort
    bus: BusPort
    cache: CachePort
    ingest: IngestService
    inventory: InventoryService
    metrics: MetricsService
    problems: ProblemsService
    stream: StreamService
    auth: AuthService
    _engine_client: ZabbixClient | None = None

    async def start(self) -> None:
        await self.store.open()

    async def stop(self) -> None:
        await self.store.close()
        await self.bus.close()
        await self.cache.close()
        if self._engine_client is not None:
            await self._engine_client.aclose()


def build_store(settings: Settings) -> StorePort:
    cipher = TokenCipher(settings.token_key)
    url = settings.store_url
    if url.startswith("sqlite:///"):
        return SqliteStore(url.removeprefix("sqlite:///"), cipher)
    if url.startswith(("postgresql://", "postgres://")):
        return PostgresStore(url, cipher, retention_days=settings.store_retention_days)
    raise ValueError(f"unsupported STORE_URL scheme: {url.split(':', 1)[0]}")


def build_container(
    settings: Settings,
    *,
    engine: MonitoringEnginePort | None = None,
    store: StorePort | None = None,
) -> Container:
    """``engine`` and ``store`` can be injected (tests); otherwise built from settings."""
    client = None
    if engine is None:
        client = ZabbixClient(settings.engine_url)
        engine = ZabbixAdapter(client)
    store = store or build_store(settings)

    bus: BusPort
    cache: CachePort
    if settings.redis_url:
        bus, cache = RedisBus(settings.redis_url), RedisCache(settings.redis_url)
    else:
        bus, cache = MemoryBus(), MemoryCache()

    decoder = ConnectorDecoder()
    inventory = InventoryService(engine, cache, settings.inventory_ttl_seconds)
    signer = SessionSigner(settings.session_secret, settings.session_ttl_hours * 3600)

    return Container(
        settings=settings,
        engine=engine,
        decoder=decoder,
        store=store,
        bus=bus,
        cache=cache,
        ingest=IngestService(decoder, store, bus),
        inventory=inventory,
        metrics=MetricsService(store, inventory),
        problems=ProblemsService(store, inventory),
        stream=StreamService(bus, inventory),
        auth=AuthService(store, signer),
        _engine_client=client,
    )
