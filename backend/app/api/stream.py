"""Server-Sent Events: GET /api/stream.

Each message is one ``data:`` line of JSON, the same shape as the REST API.
Heartbeats are sent as SSE comments (``: heartbeat``), which EventSource
ignores but which keep proxies from closing an idle connection.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import ContainerDep, TenantDep
from app.services.stream import HEARTBEAT

router = APIRouter(prefix="/api", tags=["stream"])


@router.get("/stream")
async def stream(tenant: TenantDep, container: ContainerDep) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        yield ": connected\n\n"
        async for message in container.stream.events(tenant):
            if message is HEARTBEAT:
                yield ": heartbeat\n\n"
            else:
                yield f"event: {message['type']}\ndata: {json.dumps(message)}\n\n"

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
