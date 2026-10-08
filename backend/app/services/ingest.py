"""Push path: one batch in -> store -> bus.

Order matters: write to the store first, publish second. If the store write
fails the request fails, the sender retries, and nobody was told about a
change that was never saved.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from app.domain.models import MetricPoint, Problem
from app.domain.ports import BusPort, PushDecoderPort, StorePort
from app.services.views import point_view, problem_view

log = logging.getLogger(__name__)


class IngestService:
    def __init__(self, decoder: PushDecoderPort, store: StorePort, bus: BusPort) -> None:
        self._decoder = decoder
        self._store = store
        self._bus = bus

    async def values(self, body: bytes) -> int:
        points = self._decoder.decode_values(body)
        await self._store.write_metrics(points)

        by_device: dict[str, list[MetricPoint]] = defaultdict(list)
        for p in points:
            by_device[p.device_ref].append(p)
        for device_ref, device_points in by_device.items():
            await self._bus.publish({
                "type": "metrics",
                "device_ref": device_ref,
                "points": [point_view(p) for p in device_points],
            })
        return len(points)

    async def events(self, body: bytes) -> int:
        handled = 0
        for item in self._decoder.decode_events(body):
            if isinstance(item, Problem):
                await self._store.open_problem(item)
                changed: Problem | None = item
            else:
                changed = await self._store.resolve_problem(item)
                if changed is None:
                    # The problem line never reached us (sent before we were
                    # listening, or lost). Nothing to resolve; say so and move on.
                    log.warning("resolution for unknown problem %s ignored", item.problem_ref)
                    continue
            await self._bus.publish({
                "type": "problem",
                "device_ref": changed.device_ref,
                "problem": problem_view(changed),
            })
            handled += 1
        return handled
