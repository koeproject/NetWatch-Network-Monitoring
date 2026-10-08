"""StorePort on PostgreSQL + TimescaleDB — the appliance store.

Connects as role ``acme_app`` to database ``acme``: a separate database from
the engine's, with a role that cannot connect to the engine's database at all
(CLAUDE.md §3). Both are created once by ``ops/init-store.sh``.

- ``metric_points`` is a hypertable; downsampling is ``time_bucket()`` here,
  never in the engine's API.
- Raw points older than ``retention_days`` are dropped by a TimescaleDB
  retention job (decision: docs/decisions/0007-store-placement-and-retention.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

import asyncpg

from app.crypto import TokenCipher
from app.domain.enums import Severity
from app.domain.models import (
    MetricPoint,
    Problem,
    ProblemResolution,
    Tenant,
    User,
)

# Arbitrary constant: the advisory-lock key that serialises schema set-up.
_SCHEMA_LOCK = 0x61636D65  # "acme"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_points (
    device_ref TEXT             NOT NULL,
    metric     TEXT             NOT NULL,
    ts         TIMESTAMPTZ      NOT NULL,
    value      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (device_ref, metric, ts)
);
SELECT create_hypertable('metric_points', by_range('ts'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS latest_values (
    device_ref TEXT             NOT NULL,
    metric     TEXT             NOT NULL,
    ts         TIMESTAMPTZ      NOT NULL,
    value      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (device_ref, metric)
);
CREATE TABLE IF NOT EXISTS problems (
    ref         TEXT PRIMARY KEY,
    device_ref  TEXT        NOT NULL,
    severity    SMALLINT    NOT NULL,
    title       TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS problems_device ON problems (device_ref, started_at);
CREATE TABLE IF NOT EXISTS tenants (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    token_cipher TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants (id),
    password_hash TEXT NOT NULL
);
"""


def _problem(row: asyncpg.Record) -> Problem:
    return Problem(
        ref=row["ref"],
        device_ref=row["device_ref"],
        severity=Severity(row["severity"]),
        title=row["title"],
        started_at=row["started_at"],
        resolved_at=row["resolved_at"],
    )


class PostgresStore:
    def __init__(self, dsn: str, cipher: TokenCipher, *, retention_days: int) -> None:
        self._dsn = dsn
        self._cipher = cipher
        self._retention = timedelta(days=retention_days)
        self._pool: asyncpg.Pool | None = None

    @property
    def _db(self) -> asyncpg.Pool:
        assert self._pool is not None, "store not opened"
        return self._pool

    # -- lifecycle --------------------------------------------------------------
    async def open(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)
        async with self._db.acquire() as conn, conn.transaction():
            # Every uvicorn worker runs this at start-up. Without the lock two
            # concurrent "CREATE TABLE IF NOT EXISTS" can still collide.
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK)
            await conn.execute(_SCHEMA)
            await conn.execute(
                "SELECT add_retention_policy('metric_points', $1::interval, if_not_exists => TRUE)",
                self._retention,
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # -- write path -------------------------------------------------------------
    async def write_metrics(self, points: Sequence[MetricPoint]) -> None:
        rows = [(p.device_ref, p.metric, p.ts, p.value) for p in points]
        if not rows:
            return
        async with self._db.acquire() as conn, conn.transaction():
            await conn.executemany(
                "INSERT INTO metric_points VALUES ($1,$2,$3,$4) "
                "ON CONFLICT (device_ref, metric, ts) DO UPDATE SET value = excluded.value",
                rows,
            )
            # Only move "latest" forward: a retried old batch must not win.
            await conn.executemany(
                "INSERT INTO latest_values VALUES ($1,$2,$3,$4) "
                "ON CONFLICT (device_ref, metric) DO UPDATE "
                "SET ts = excluded.ts, value = excluded.value "
                "WHERE excluded.ts >= latest_values.ts",
                rows,
            )

    async def open_problem(self, problem: Problem) -> None:
        await self._db.execute(
            "INSERT INTO problems VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (ref) DO NOTHING",
            problem.ref,
            problem.device_ref,
            int(problem.severity),
            problem.title,
            problem.started_at,
            problem.resolved_at,
        )

    async def resolve_problem(self, resolution: ProblemResolution) -> Problem | None:
        async with self._db.acquire() as conn:
            await conn.execute(
                "UPDATE problems SET resolved_at = $1 WHERE ref = $2 AND resolved_at IS NULL",
                resolution.resolved_at,
                resolution.problem_ref,
            )
            row = await conn.fetchrow(
                "SELECT * FROM problems WHERE ref = $1", resolution.problem_ref
            )
        return None if row is None else _problem(row)

    # -- read path --------------------------------------------------------------
    async def series(
        self,
        device_ref: str,
        metric: str,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> list[MetricPoint]:
        rows = await self._db.fetch(
            "SELECT time_bucket($1::interval, ts) AS bucket, avg(value) AS value "
            "FROM metric_points "
            "WHERE device_ref = $2 AND metric = $3 AND ts >= $4 AND ts < $5 "
            "GROUP BY bucket ORDER BY bucket",
            timedelta(seconds=step_seconds),
            device_ref,
            metric,
            start,
            end,
        )
        return [MetricPoint(device_ref, metric, r["bucket"], r["value"]) for r in rows]

    async def latest(self, device_refs: Iterable[str]) -> list[MetricPoint]:
        rows = await self._db.fetch(
            "SELECT * FROM latest_values WHERE device_ref = ANY($1::text[]) "
            "ORDER BY device_ref, metric",
            list(device_refs),
        )
        return [MetricPoint(r["device_ref"], r["metric"], r["ts"], r["value"]) for r in rows]

    async def problems(
        self,
        device_refs: Iterable[str],
        *,
        active_only: bool,
        limit: int,
    ) -> list[Problem]:
        rows = await self._db.fetch(
            "SELECT * FROM problems WHERE device_ref = ANY($1::text[]) "
            "AND (NOT $2 OR resolved_at IS NULL) "
            "ORDER BY resolved_at IS NOT NULL, severity DESC, started_at DESC LIMIT $3",
            list(device_refs),
            active_only,
            limit,
        )
        return [_problem(r) for r in rows]

    # -- portal accounts ----------------------------------------------------------
    async def save_tenant(self, tenant: Tenant) -> None:
        await self._db.execute(
            "INSERT INTO tenants VALUES ($1,$2,$3) ON CONFLICT (id) DO UPDATE "
            "SET name = excluded.name, token_cipher = excluded.token_cipher",
            tenant.id,
            tenant.name,
            self._cipher.encrypt(tenant.engine_token),
        )

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        row = await self._db.fetchrow("SELECT * FROM tenants WHERE id = $1", tenant_id)
        if row is None:
            return None
        return Tenant(row["id"], row["name"], self._cipher.decrypt(row["token_cipher"]))

    async def save_user(self, user: User) -> None:
        await self._db.execute(
            "INSERT INTO users VALUES ($1,$2,$3) ON CONFLICT (username) DO UPDATE "
            "SET tenant_id = excluded.tenant_id, password_hash = excluded.password_hash",
            user.username,
            user.tenant_id,
            user.password_hash,
        )

    async def get_user(self, username: str) -> User | None:
        row = await self._db.fetchrow("SELECT * FROM users WHERE username = $1", username)
        return None if row is None else User(row["username"], row["tenant_id"], row["password_hash"])
