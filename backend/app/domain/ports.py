"""Ports: what the services layer may ask of the outside world.

Services depend on these Protocols only. The concrete classes live in the
engine package, ``store/``, ``bus/`` and ``cache.py``, and are wired
together in ``container.py``.

``MonitoringEnginePort`` is deliberately configuration/lookup only. It has
no method that returns a time series or past values: graphs, tiles and the
live stream read from our own store, fed by the push path (CLAUDE.md §3,
ADR 0005). If a ``get_history`` ever feels necessary here, that is the
signal that §3 is about to be broken.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.domain.models import (
    Device,
    MetricPoint,
    Problem,
    ProblemResolution,
    Tenant,
    User,
)


class DeviceNotFound(LookupError):
    def __init__(self, ref: str) -> None:
        super().__init__(f"device not found: {ref}")
        self.ref = ref


class EngineUnavailable(RuntimeError):
    """The monitoring engine could not answer a lookup (down, timeout, or an
    API error). Implementations translate their own errors into this, so the
    API layer can answer 502 without knowing what the engine is."""


@runtime_checkable
class MonitoringEnginePort(Protocol):
    """Lookups against the monitoring engine.

    The token is passed on every call (ADR 0004): the read path uses the
    tenant's own token, so the engine's permissions are a second line of
    defence. An implementation must never fall back to a token of its own.
    """

    async def list_devices(self, token: str) -> list[Device]: ...

    async def get_device(self, ref: str, token: str) -> Device:
        """Raise DeviceNotFound if the ref is unknown or not visible to this token."""
        ...


@runtime_checkable
class PushDecoderPort(Protocol):
    """Turns one pushed batch (raw request body) into domain objects.

    Bad lines are logged and skipped; one bad line never drops the batch.
    """

    def decode_values(self, body: bytes) -> list[MetricPoint]: ...

    def decode_events(self, body: bytes) -> list[Problem | ProblemResolution]: ...


@runtime_checkable
class StorePort(Protocol):
    """Our own database. The only source for graphs, tiles and problems."""

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    # -- write path (ingest) ------------------------------------------------
    async def write_metrics(self, points: Sequence[MetricPoint]) -> None:
        """Upsert on (device_ref, metric, ts): the push may retry a batch."""
        ...

    async def open_problem(self, problem: Problem) -> None: ...

    async def resolve_problem(self, resolution: ProblemResolution) -> Problem | None:
        """Mark a stored problem resolved and return it, or None if unknown."""
        ...

    # -- read path ----------------------------------------------------------
    async def series(
        self,
        device_ref: str,
        metric: str,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> list[MetricPoint]:
        """Average per ``step_seconds`` bucket; ``ts`` is the bucket start."""
        ...

    async def latest(self, device_refs: Iterable[str]) -> list[MetricPoint]: ...

    async def problems(
        self,
        device_refs: Iterable[str],
        *,
        active_only: bool,
        limit: int,
    ) -> list[Problem]: ...

    # -- portal accounts ----------------------------------------------------
    async def save_tenant(self, tenant: Tenant) -> None: ...

    async def get_tenant(self, tenant_id: str) -> Tenant | None: ...

    async def save_user(self, user: User) -> None: ...

    async def get_user(self, username: str) -> User | None: ...


@runtime_checkable
class BusPort(Protocol):
    """Fan-out of live updates to every SSE connection, across workers."""

    async def publish(self, message: dict[str, Any]) -> None: ...

    def subscribe(self) -> AbstractAsyncContextManager[AsyncIterator[dict[str, Any]]]: ...

    async def close(self) -> None: ...


@runtime_checkable
class CachePort(Protocol):
    async def get(self, key: str) -> Any | None: ...

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...

    async def close(self) -> None: ...
