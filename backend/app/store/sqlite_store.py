"""StorePort on SQLite — tests and the demo.

Uses the stdlib ``sqlite3`` module. Every call runs in a worker thread
(``asyncio.to_thread``) behind a lock, so the event loop never blocks on disk
and the one connection is never used by two threads at once.

Times are stored as UTC epoch seconds (REAL) and converted back to aware
datetimes on the way out.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from app.crypto import TokenCipher
from app.domain.enums import Severity
from app.domain.models import (
    MetricPoint,
    Problem,
    ProblemResolution,
    Tenant,
    User,
)

T = TypeVar("T")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS metric_points (
    device_ref TEXT NOT NULL,
    metric     TEXT NOT NULL,
    ts         REAL NOT NULL,
    value      REAL NOT NULL,
    PRIMARY KEY (device_ref, metric, ts)
);
CREATE TABLE IF NOT EXISTS latest_values (
    device_ref TEXT NOT NULL,
    metric     TEXT NOT NULL,
    ts         REAL NOT NULL,
    value      REAL NOT NULL,
    PRIMARY KEY (device_ref, metric)
);
CREATE TABLE IF NOT EXISTS problems (
    ref         TEXT PRIMARY KEY,
    device_ref  TEXT NOT NULL,
    severity    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    started_at  REAL NOT NULL,
    resolved_at REAL
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


def _epoch(ts: datetime) -> float:
    return ts.timestamp()


def _dt(epoch: float | None) -> datetime | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, tz=UTC)


def _problem(row: sqlite3.Row) -> Problem:
    return Problem(
        ref=row["ref"],
        device_ref=row["device_ref"],
        severity=Severity(row["severity"]),
        title=row["title"],
        started_at=_dt(row["started_at"]),  # type: ignore[arg-type]
        resolved_at=_dt(row["resolved_at"]),
    )


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


class SqliteStore:
    def __init__(self, path: str | Path, cipher: TokenCipher) -> None:
        self._path = str(path)
        self._cipher = cipher
        self._db: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        assert self._db is not None, "store not opened"
        db = self._db
        async with self._lock:
            return await asyncio.to_thread(fn, db)

    # -- lifecycle --------------------------------------------------------------
    async def open(self) -> None:
        def connect() -> sqlite3.Connection:
            db = sqlite3.connect(self._path, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(_SCHEMA)
            return db

        self._db = await asyncio.to_thread(connect)

    async def close(self) -> None:
        if self._db is not None:
            await asyncio.to_thread(self._db.close)
            self._db = None

    # -- write path -------------------------------------------------------------
    async def write_metrics(self, points: Sequence[MetricPoint]) -> None:
        rows = [(p.device_ref, p.metric, _epoch(p.ts), p.value) for p in points]
        if not rows:
            return

        def write(db: sqlite3.Connection) -> None:
            with db:
                db.executemany(
                    "INSERT INTO metric_points VALUES (?,?,?,?) "
                    "ON CONFLICT (device_ref, metric, ts) DO UPDATE SET value = excluded.value",
                    rows,
                )
                # Only move "latest" forward: a retried old batch must not win.
                db.executemany(
                    "INSERT INTO latest_values VALUES (?,?,?,?) "
                    "ON CONFLICT (device_ref, metric) DO UPDATE "
                    "SET ts = excluded.ts, value = excluded.value "
                    "WHERE excluded.ts >= latest_values.ts",
                    rows,
                )

        await self._run(write)

    async def open_problem(self, problem: Problem) -> None:
        row = (
            problem.ref,
            problem.device_ref,
            int(problem.severity),
            problem.title,
            _epoch(problem.started_at),
            None if problem.resolved_at is None else _epoch(problem.resolved_at),
        )

        def write(db: sqlite3.Connection) -> None:
            with db:
                db.execute(
                    "INSERT INTO problems VALUES (?,?,?,?,?,?) ON CONFLICT (ref) DO NOTHING",
                    row,
                )

        await self._run(write)

    async def resolve_problem(self, resolution: ProblemResolution) -> Problem | None:
        def write(db: sqlite3.Connection) -> Problem | None:
            with db:
                db.execute(
                    "UPDATE problems SET resolved_at = ? WHERE ref = ? AND resolved_at IS NULL",
                    (_epoch(resolution.resolved_at), resolution.problem_ref),
                )
            row = db.execute(
                "SELECT * FROM problems WHERE ref = ?", (resolution.problem_ref,)
            ).fetchone()
            return None if row is None else _problem(row)

        return await self._run(write)

    # -- read path --------------------------------------------------------------
    async def series(
        self,
        device_ref: str,
        metric: str,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> list[MetricPoint]:
        def read(db: sqlite3.Connection) -> list[MetricPoint]:
            rows = db.execute(
                "SELECT CAST(ts / :step AS INTEGER) * :step AS bucket, AVG(value) AS value "
                "FROM metric_points "
                "WHERE device_ref = :d AND metric = :m AND ts >= :start AND ts < :end "
                "GROUP BY bucket ORDER BY bucket",
                {"step": step_seconds, "d": device_ref, "m": metric,
                 "start": _epoch(start), "end": _epoch(end)},
            ).fetchall()
            return [
                MetricPoint(device_ref, metric, _dt(r["bucket"]), r["value"])  # type: ignore[arg-type]
                for r in rows
            ]

        return await self._run(read)

    async def latest(self, device_refs: Iterable[str]) -> list[MetricPoint]:
        refs = list(device_refs)
        if not refs:
            return []

        def read(db: sqlite3.Connection) -> list[MetricPoint]:
            rows = db.execute(
                f"SELECT * FROM latest_values WHERE device_ref IN ({_placeholders(len(refs))}) "
                "ORDER BY device_ref, metric",
                refs,
            ).fetchall()
            return [
                MetricPoint(r["device_ref"], r["metric"], _dt(r["ts"]), r["value"])  # type: ignore[arg-type]
                for r in rows
            ]

        return await self._run(read)

    async def problems(
        self,
        device_refs: Iterable[str],
        *,
        active_only: bool,
        limit: int,
    ) -> list[Problem]:
        refs = list(device_refs)
        if not refs:
            return []
        where = f"device_ref IN ({_placeholders(len(refs))})"
        if active_only:
            where += " AND resolved_at IS NULL"

        def read(db: sqlite3.Connection) -> list[Problem]:
            rows = db.execute(
                f"SELECT * FROM problems WHERE {where} "
                "ORDER BY resolved_at IS NOT NULL, severity DESC, started_at DESC LIMIT ?",
                [*refs, limit],
            ).fetchall()
            return [_problem(r) for r in rows]

        return await self._run(read)

    # -- portal accounts ----------------------------------------------------------
    async def save_tenant(self, tenant: Tenant) -> None:
        row = (tenant.id, tenant.name, self._cipher.encrypt(tenant.engine_token))

        def write(db: sqlite3.Connection) -> None:
            with db:
                db.execute(
                    "INSERT INTO tenants VALUES (?,?,?) ON CONFLICT (id) DO UPDATE "
                    "SET name = excluded.name, token_cipher = excluded.token_cipher",
                    row,
                )

        await self._run(write)

    async def get_tenant(self, tenant_id: str) -> Tenant | None:
        def read(db: sqlite3.Connection) -> Any:
            return db.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()

        row = await self._run(read)
        if row is None:
            return None
        return Tenant(row["id"], row["name"], self._cipher.decrypt(row["token_cipher"]))

    async def save_user(self, user: User) -> None:
        row = (user.username, user.tenant_id, user.password_hash)

        def write(db: sqlite3.Connection) -> None:
            with db:
                db.execute(
                    "INSERT INTO users VALUES (?,?,?) ON CONFLICT (username) DO UPDATE "
                    "SET tenant_id = excluded.tenant_id, password_hash = excluded.password_hash",
                    row,
                )

        await self._run(write)

    async def get_user(self, username: str) -> User | None:
        def read(db: sqlite3.Connection) -> Any:
            return db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        row = await self._run(read)
        return None if row is None else User(row["username"], row["tenant_id"], row["password_hash"])
