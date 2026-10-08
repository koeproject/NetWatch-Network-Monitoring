"""The single place that translates between the engine's world and our domain.

Only this module knows what is inside a ``device_ref`` or ``problem_ref``.
Everything past it sees opaque strings and timezone-aware datetimes.

- device_ref  = the engine's technical host name (ADR 0006). The Connector
  push carries host names, not hostids, so this lets ingest map a pushed
  line to a device without one API call per line.
- problem_ref = "P" + the problem event's eventid.

Ignores ``lastvalue`` / ``lastclock`` / ``prevvalue`` on purpose (ADR 0005):
latest values come from our store, on the same path as the graphs.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.enums import DeviceKind, DeviceStatus, Severity
from app.domain.models import Device, MetricPoint, Problem, ProblemResolution
from app.zabbix.connector_schema import (
    NUMERIC_VALUE_TYPES,
    ProblemLine,
    RecoveryLine,
    ValueLine,
)

_PROBLEM_PREFIX = "P"

# Engine trigger priority (0 Not classified … 5 Disaster) -> ours.
_SEVERITY = {
    0: Severity.INFO,
    1: Severity.INFO,
    2: Severity.WARNING,
    3: Severity.MINOR,
    4: Severity.MAJOR,
    5: Severity.CRITICAL,
}

# Host tag "role" (set by provisioning, Phase 2) -> ours.
_KIND = {
    "core": DeviceKind.CORE_SWITCH,
    "access": DeviceKind.ACCESS_SWITCH,
    "ap": DeviceKind.ACCESS_POINT,
    "server": DeviceKind.SERVER,
}

# host.get: status 0 = monitored, 1 = not monitored; maintenance_status 1 = in
# maintenance; interface available 0 = unknown, 1 = available, 2 = unavailable.
_HOST_DISABLED = "1"
_IN_MAINTENANCE = "1"
_IF_AVAILABLE = "1"
_IF_UNAVAILABLE = "2"


# -- refs -------------------------------------------------------------------
def device_ref(host: str) -> str:
    return host


def host_from_device_ref(ref: str) -> str:
    return ref


def problem_ref(eventid: int | str) -> str:
    return f"{_PROBLEM_PREFIX}{int(eventid)}"


def eventid_from_problem_ref(ref: str) -> int:
    if not ref.startswith(_PROBLEM_PREFIX) or not ref[1:].isdigit():
        raise ValueError(f"not a problem ref: {ref!r}")
    return int(ref[1:])


# -- scalars ----------------------------------------------------------------
def to_datetime(seconds: int, nanos: int = 0) -> datetime:
    """Engine (seconds, nanoseconds) -> aware UTC datetime, microsecond precision."""
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(microseconds=nanos // 1000)


def severity(priority: int) -> Severity:
    return _SEVERITY.get(priority, Severity.WARNING)


# -- JSON-RPC objects ---------------------------------------------------------
def _tag(tags: list[Mapping[str, Any]], name: str) -> str:
    for t in tags:
        if t.get("tag") == name:
            return str(t.get("value", ""))
    return ""


def _status(host: Mapping[str, Any]) -> DeviceStatus:
    if str(host.get("status")) == _HOST_DISABLED:
        return DeviceStatus.DISABLED
    if str(host.get("maintenance_status")) == _IN_MAINTENANCE:
        return DeviceStatus.MAINTENANCE
    states = {str(i.get("available")) for i in host.get("interfaces", [])}
    if _IF_AVAILABLE in states:
        return DeviceStatus.UP
    if _IF_UNAVAILABLE in states:
        return DeviceStatus.DOWN
    return DeviceStatus.UNKNOWN


def device_from_api(host: Mapping[str, Any]) -> Device:
    """One object from host.get (with selectInterfaces and selectTags)."""
    tags = host.get("tags", [])
    return Device(
        ref=device_ref(host["host"]),
        name=host.get("name") or host["host"],
        kind=_KIND.get(_tag(tags, "role"), DeviceKind.OTHER),
        site=_tag(tags, "site"),
        status=_status(host),
    )


# -- Connector lines ----------------------------------------------------------
def metric_from_value(line: ValueLine) -> MetricPoint | None:
    """Numeric items only. Character, log and text values are not metrics."""
    if line.type not in NUMERIC_VALUE_TYPES or isinstance(line.value, str):
        return None
    return MetricPoint(
        device_ref=device_ref(line.host.host),
        metric=line.name,
        ts=to_datetime(line.clock, line.ns),
        value=float(line.value),
    )


def problem_from_event(line: ProblemLine) -> Problem:
    # A trigger can span several hosts; the problem is filed under the first.
    return Problem(
        ref=problem_ref(line.eventid),
        device_ref=device_ref(line.hosts[0].host),
        severity=severity(line.severity),
        title=line.name,
        started_at=to_datetime(line.clock, line.ns),
    )


def resolution_from_event(line: RecoveryLine) -> ProblemResolution:
    return ProblemResolution(
        problem_ref=problem_ref(line.p_eventid),
        resolved_at=to_datetime(line.clock, line.ns),
    )
