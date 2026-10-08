"""Domain objects -> plain JSON-ready dicts.

One shape per object, shared by the HTTP API, the live stream and the cache,
so a tile, a list row and an SSE message always look the same.
"""

from __future__ import annotations

from typing import Any

from app.domain.enums import DeviceKind, DeviceStatus
from app.domain.models import Device, MetricPoint, Problem


def device_view(d: Device) -> dict[str, Any]:
    return {
        "ref": d.ref,
        "name": d.name,
        "kind": d.kind.value,
        "site": d.site,
        "status": d.status.value,
    }


def device_from_view(v: dict[str, Any]) -> Device:
    return Device(
        ref=v["ref"],
        name=v["name"],
        kind=DeviceKind(v["kind"]),
        site=v["site"],
        status=DeviceStatus(v["status"]),
    )


def point_view(p: MetricPoint) -> dict[str, Any]:
    return {"metric": p.metric, "ts": p.ts.isoformat(), "value": p.value}


def problem_view(p: Problem) -> dict[str, Any]:
    return {
        "ref": p.ref,
        "device_ref": p.device_ref,
        "severity": p.severity.name.lower(),
        "title": p.title,
        "started_at": p.started_at.isoformat(),
        "resolved_at": None if p.resolved_at is None else p.resolved_at.isoformat(),
        "active": p.is_active,
    }
