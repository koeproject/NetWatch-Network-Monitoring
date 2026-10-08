# 0007 — Where our store lives, and how long it keeps data

- Status: **Accepted for Phase 1**; retention to be confirmed with the
  customer before Phase 4.
- Date: 2026-10-09 (Phase 1.4)
- Affects: `ops/init-store.sh`, `backend/app/store/postgres_store.py`,
  `backend/app/config.py` (`STORE_URL`, `STORE_RETENTION_DAYS`)

Closes the two "new" open decisions in rebuild-plan §8 that block 1.4.

## Decision 1 — placement

A **separate database `acme`** with its own role **`acme_app`**, inside the
**same PostgreSQL instance** as the engine (the `db` container).

- `acme_app` is LOGIN only: not superuser, cannot create databases or roles.
- `REVOKE CONNECT ON DATABASE zabbix FROM PUBLIC`: `acme_app` cannot even
  open a connection to the engine's database. Verified:
  `psql -U acme_app -d zabbix` → `FATAL: permission denied for database "zabbix"`.
- The `timescaledb` extension is created in `acme` by the admin role once
  (`ops/init-store.sh`); tables are created by the app as owner.

Why not a separate container now: one instance is less to run, back up and
monitor in Phase 1. The separation that matters (CLAUDE.md §3) is the
database + role boundary, and that holds. Revisit for the appliance if the
engine's DB load and ours compete (Phase 4) — moving is a `pg_dump` of one
database and a new `STORE_URL`.

## Decision 2 — retention

- Raw `metric_points`: **30 days** (`STORE_RETENTION_DAYS`, default 30),
  enforced by a TimescaleDB retention job added at start-up.
- `problems`, `latest_values`, accounts: kept (small).
- No continuous aggregates yet; graphs downsample at query time with
  `time_bucket()`. Add hourly aggregates kept for 12 months when the
  customer asks for long-range reports.

## Verification

```bash
docker compose -f engine/docker-compose.yml exec -T db \
  psql -U acme_app -d zabbix -c "select 1"          # expect: permission denied
docker compose -f engine/docker-compose.yml exec -T db psql -U acme_app -d acme \
  -tAc "select hypertable_name from timescaledb_information.hypertables"
                                                     # expect: metric_points
docker compose -f engine/docker-compose.yml exec -T db psql -U acme_app -d acme \
  -tAc "select proc_name, config from timescaledb_information.jobs where hypertable_name='metric_points'"
                                                     # expect: policy_retention | {"drop_after": "30 days", ...}
```
