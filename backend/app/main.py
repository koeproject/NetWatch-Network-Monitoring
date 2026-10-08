"""ASGI app.

    cd backend
    .venv\\Scripts\\python -m uvicorn app.main:app --port 8000

Settings are read when the app starts (lifespan), not on import, so tests can
build an app around their own container.

Also serves the built portal (FRONTEND_DIST, Phase 3) when it exists.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse

from app.api import auth, devices, hooks, problems, stream
from app.config import get_settings
from app.container import Container, build_container
from app.domain.ports import DeviceNotFound, EngineUnavailable

log = logging.getLogger("app")


def create_app(container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        c = container or build_container(get_settings())
        await c.start()
        app.state.container = c
        try:
            yield
        finally:
            await c.stop()

    app = FastAPI(title="acme-nms", lifespan=lifespan)

    @app.exception_handler(DeviceNotFound)
    async def _not_found(_: Request, exc: DeviceNotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)

    @app.exception_handler(EngineUnavailable)
    async def _engine_down(_: Request, exc: EngineUnavailable) -> JSONResponse:
        log.error("engine lookup failed: %s", exc)
        return JSONResponse(
            {"detail": "monitoring backend unavailable"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    for module in (hooks, auth, devices, problems, stream):
        app.include_router(module.router)

    @app.get("/{path:path}", include_in_schema=False)
    async def portal(path: str, request: Request) -> FileResponse:
        """Single-page app: real files as-is, any other path -> index.html."""
        if path.startswith(("api/", "hooks/")):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        dist = Path(request.app.state.container.settings.frontend_dist).resolve()
        index = dist / "index.html"
        if not index.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "portal not built")
        candidate = (dist / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(index)

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
