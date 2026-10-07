# 0002 — TimescaleDB version pin

- Status: **Accepted**
- Date: 2026-10-08 (rebuild; same pin as the previous build)
- Affects: `engine/docker-compose.yml`

## Context

Zabbix supports TimescaleDB only inside a range that depends on the Zabbix
patch release (CLAUDE.md §7): 2.13.0 up to a ceiling that rises per patch —
2.28.X is the ceiling for 7.0.29, 2.29.X needs 7.0.30. Floating tags such as
`timescale/timescaledb:latest-pg16` resolve to whatever is newest and can
land outside that range, at which point the server logs "unsupported".

## Decision

Pin full tags, as a pair:

| Image | Tag |
|---|---|
| `timescale/timescaledb` | `2.28.3-pg16` |
| `zabbix/zabbix-server-pgsql` | `alpine-7.0.29` |
| `zabbix/zabbix-web-nginx-pgsql` | `alpine-7.0.29` |

PostgreSQL 16 sits inside the supported 13–18 range. 2.28.3 is the newest
TimescaleDB that 7.0.29 accepts.

## Consequences

- The two tags move together. Raising TimescaleDB to 2.29.X requires Zabbix
  7.0.30 or later first.
- `ENABLE_TIMESCALEDB=true` only takes effect on the first start against an
  empty database; an existing volume keeps its hypertable layout.
- Compression is TimescaleDB Community (TSL): free for on-prem delivery, not
  resellable as a hosted service.

## Verification (run 2026-10-08, see `docs/phase-0-checklist.md` A.2)

```bash
docker compose -f engine/docker-compose.yml exec -T db psql -U zabbix -d zabbix \
  -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"
# got: 2.28.3
docker compose -f engine/docker-compose.yml logs zabbix-server | grep -i timescale
# got: "TimescaleDB version 2.28.3 is valid", no "unsupported"
```
