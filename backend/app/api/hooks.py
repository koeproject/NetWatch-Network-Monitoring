"""Receiver for the monitoring engine's push (CLAUDE.md §3).

Transport shell only: check the Bearer token, read the body, hand it to the
ingest service, answer. No payload schema here — decoding is behind
PushDecoderPort, wired in container.py.

Status codes are chosen for the sender's retry logic:
- 200: stored (lines that failed to decode were logged and skipped).
- 401: wrong token — retrying will not help; fix the configuration.
- 503: our store failed — retry later; writes are idempotent, so a
       repeated batch does not duplicate anything.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import ContainerDep

log = logging.getLogger(__name__)

router = APIRouter(prefix="/hooks", tags=["hooks"])


def _check_token(request: Request, expected: str) -> None:
    given = request.headers.get("Authorization", "")
    if not hmac.compare_digest(given.encode(), f"Bearer {expected}".encode()):
        log.warning("push to %s rejected: bad or missing Bearer token", request.url.path)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")


@router.post("/values")
async def push_values(request: Request, container: ContainerDep) -> dict[str, int]:
    _check_token(request, container.settings.push_token)
    body = await request.body()
    try:
        stored = await container.ingest.values(body)
    except Exception as exc:
        log.exception("value batch not stored")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from exc
    log.info("values batch: %d bytes, %d points stored", len(body), stored)
    return {"stored": stored}


@router.post("/events")
async def push_events(request: Request, container: ContainerDep) -> dict[str, int]:
    _check_token(request, container.settings.push_token)
    body = await request.body()
    try:
        handled = await container.ingest.events(body)
    except Exception as exc:
        log.exception("event batch not stored")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "store unavailable") from exc
    log.info("events batch: %d bytes, %d events handled", len(body), handled)
    return {"handled": handled}
