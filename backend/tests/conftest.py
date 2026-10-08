from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    # Async tests run on asyncio only (the same loop uvicorn uses).
    return "asyncio"
