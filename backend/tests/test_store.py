"""1.4 — one contract, run against every StorePort implementation.

SQLite always runs. Postgres runs only when TEST_POSTGRES_DSN points at an
empty scratch database with the timescaledb extension (see the Phase 1 guide);
otherwise it is skipped, never faked.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.crypto import TokenCipher
from app.domain.enums import Severity
from app.domain.models import MetricPoint, Problem, ProblemResolution, Tenant, User
from app.domain.ports import StorePort
from app.store.postgres_store import PostgresStore
from app.store.sqlite_store import SqliteStore

T0 = datetime(2026, 10, 8, 3, 0, tzinfo=UTC)
CIPHER = TokenCipher(Fernet.generate_key().decode())


@pytest.fixture(params=["sqlite", "postgres"])
async def store(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[StorePort]:
    if request.param == "sqlite":
        s: StorePort = SqliteStore(tmp_path / "store.db", CIPHER)
    else:
        dsn = os.environ.get("TEST_POSTGRES_DSN")
        if not dsn:
            pytest.skip("TEST_POSTGRES_DSN not set")
        s = PostgresStore(dsn, CIPHER, retention_days=30)
    await s.open()
    try:
        yield s
    finally:
        if request.param == "postgres":
            # Leave the scratch database empty for the next test.
            pool = s._db  # type: ignore[attr-defined]
            await pool.execute(
                "TRUNCATE metric_points, latest_values, problems, users, tenants CASCADE"
            )
        await s.close()


def _p(minute: int, value: float, ref: str = "sw1", metric: str = "cpu") -> MetricPoint:
    return MetricPoint(ref, metric, T0 + timedelta(minutes=minute), value)


@pytest.mark.anyio
async def test_store_satisfies_port(store: StorePort) -> None:
    assert isinstance(store, StorePort)


@pytest.mark.anyio
async def test_retried_batch_is_not_duplicated(store: StorePort) -> None:
    batch = [_p(0, 10), _p(1, 20)]
    await store.write_metrics(batch)
    await store.write_metrics(batch)  # the push retried

    series = await store.series("sw1", "cpu", T0, T0 + timedelta(hours=1), 60)
    assert [p.value for p in series] == [10, 20]


@pytest.mark.anyio
async def test_series_downsamples_by_step(store: StorePort) -> None:
    await store.write_metrics([_p(m, v) for m, v in [(0, 10), (1, 20), (5, 30), (6, 50)]])

    series = await store.series("sw1", "cpu", T0, T0 + timedelta(hours=1), 300)

    assert [(p.ts, p.value) for p in series] == [(T0, 15), (T0 + timedelta(minutes=5), 40)]
    assert all(p.ts.tzinfo is not None for p in series)


@pytest.mark.anyio
async def test_latest_only_moves_forward(store: StorePort) -> None:
    await store.write_metrics([_p(5, 50)])
    await store.write_metrics([_p(1, 10)])  # an old batch arriving late

    (latest,) = await store.latest(["sw1"])
    assert (latest.ts, latest.value) == (T0 + timedelta(minutes=5), 50)


@pytest.mark.anyio
async def test_latest_is_filtered_by_device(store: StorePort) -> None:
    await store.write_metrics([_p(0, 1, ref="a"), _p(0, 2, ref="b")])
    assert [p.device_ref for p in await store.latest(["a"])] == ["a"]
    assert await store.latest([]) == []


@pytest.mark.anyio
async def test_problem_lifecycle(store: StorePort) -> None:
    problem = Problem("P20", "sw1", Severity.WARNING, "probe is 1", T0)
    await store.open_problem(problem)
    await store.open_problem(problem)  # retried

    assert [p.ref for p in await store.problems(["sw1"], active_only=True, limit=10)] == ["P20"]

    resolved = await store.resolve_problem(ProblemResolution("P20", T0 + timedelta(seconds=12)))
    assert resolved is not None
    assert resolved.device_ref == "sw1" and not resolved.is_active

    assert await store.problems(["sw1"], active_only=True, limit=10) == []
    assert len(await store.problems(["sw1"], active_only=False, limit=10)) == 1
    assert await store.problems(["other"], active_only=False, limit=10) == []


@pytest.mark.anyio
async def test_resolving_an_unknown_problem_returns_none(store: StorePort) -> None:
    assert await store.resolve_problem(ProblemResolution("P999", T0)) is None


@pytest.mark.anyio
async def test_tenant_token_is_encrypted_at_rest(store: StorePort, tmp_path: Path) -> None:
    await store.save_tenant(Tenant("acme-hq", "ACME HQ", "secret-read-token"))
    await store.save_user(User("alice", "acme-hq", "hash"))

    tenant = await store.get_tenant("acme-hq")
    assert tenant is not None and tenant.engine_token == "secret-read-token"
    assert (await store.get_user("alice")) == User("alice", "acme-hq", "hash")
    assert await store.get_user("nobody") is None

    if isinstance(store, SqliteStore):
        # WAL mode keeps recent writes in store.db-wal: check every file.
        files = list(tmp_path.glob("store.db*"))
        assert files
        assert all(b"secret-read-token" not in f.read_bytes() for f in files)
        assert any(b"acme-hq" in f.read_bytes() for f in files)  # the check can see rows
