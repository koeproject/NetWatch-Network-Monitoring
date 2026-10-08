"""Domain models.

Rules that hold for every class here:
- IDs are opaque strings (``ref``, ``device_ref``). Nothing outside the
  engine package's mapper may parse them.
- Every point in time is a timezone-aware ``datetime``. A naive one is
  rejected on construction, so a timezone bug fails loudly instead of
  shifting a graph by seven hours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import DeviceKind, DeviceStatus, Severity


def _require_aware(field: str, value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware, got naive {value!r}")


@dataclass(frozen=True, slots=True)
class Device:
    ref: str
    name: str
    kind: DeviceKind
    site: str
    status: DeviceStatus


@dataclass(frozen=True, slots=True)
class MetricPoint:
    device_ref: str
    metric: str
    ts: datetime
    value: float

    def __post_init__(self) -> None:
        _require_aware("ts", self.ts)


@dataclass(frozen=True, slots=True)
class Problem:
    ref: str
    device_ref: str
    severity: Severity
    title: str
    started_at: datetime
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware("started_at", self.started_at)
        _require_aware("resolved_at", self.resolved_at)

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None


@dataclass(frozen=True, slots=True)
class ProblemResolution:
    """A problem ended. Carries only what the push tells us at that moment;
    the store fills in the rest from the problem it already holds."""

    problem_ref: str
    resolved_at: datetime

    def __post_init__(self) -> None:
        _require_aware("resolved_at", self.resolved_at)


@dataclass(frozen=True, slots=True)
class Tenant:
    """A customer. ``engine_token`` is the tenant's own read token (ADR 0004);
    it never leaves the backend."""

    id: str
    name: str
    engine_token: str


@dataclass(frozen=True, slots=True)
class User:
    username: str
    tenant_id: str
    password_hash: str
