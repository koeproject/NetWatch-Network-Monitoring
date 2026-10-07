# 0005 — Where a "latest value" comes from

- Status: **Accepted** (CLAUDE.md §8 #5)
- Date: 2026-10-08 (rewritten for the rebuild)
- Affects: `backend/app/zabbix/adapter.py`, `backend/app/zabbix/mapper.py`,
  `backend/app/store/`, frontend tiles

## Context

`item.get` with `output: "extend"` returns `lastvalue`, `lastclock` and
`prevvalue` on Zabbix 7.0.29 — verified again on the rebuilt engine
(`docs/phase-0-checklist.md` A.3). So a status tile *could* read the latest
value straight from the API.

Against that (CLAUDE.md §3):

- `item.get` gives one value per item, never a series. The graph under a tile
  must come from our store anyway.
- Every API call goes through the engine's PHP frontend and competes with its
  UI workers.
- A tile from `item.get` and a chart from our store are two sources; they can
  disagree (different moments, different rounding, connector lag).

## Decision

Latest values come from **our own store**, filled by the Connector push, on
the same path as the graphs. `mapper.device_from_api()` ignores the
`lastvalue` / `lastclock` / `prevvalue` members even though they are present.

## Consequences

- A tile and the chart beneath it read the same rows and cannot disagree.
- Until the first value for an item arrives over the Connector, its tile
  shows "no data" rather than falling back to `item.get`.
- Connector lag is visible on tiles; it is monitored via
  `zabbix[connector_queue]` (Phase 4 health check).
