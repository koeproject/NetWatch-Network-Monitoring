# 0006 — `device_ref` is the engine's technical host name

- Status: **Accepted**
- Date: 2026-10-09 (Phase 1.3)
- Affects: `backend/app/zabbix/mapper.py` (the only place that knows this)

## Context

`device_ref` must be an opaque string that only `zabbix/mapper.py` can
interpret (CLAUDE.md §4). The obvious content is the engine's `hostid`, but
the Connector push does **not** carry a hostid: value lines carry
`host.host` (technical name) and event lines carry `hosts[].host`
(`docs/connector-payload.md`). Using hostid would mean one API lookup
(name → hostid) per pushed line, or a cache that can go stale — on the hot
ingest path.

## Decision

`device_ref` = the technical host name (`host.host`), unchanged.
`problem_ref` = `"P"` + the problem event's `eventid`.

Both are built and parsed only by `mapper.device_ref()` /
`host_from_device_ref()` / `problem_ref()` / `eventid_from_problem_ref()`.

## Consequences

- Ingest maps a pushed line to a device with zero API calls.
- **Renaming a host in the engine starts a new device** in our store: the old
  history stays under the old ref. Host names are owned by provisioning
  (`inventory.csv`, Phase 2) and must be treated as permanent IDs.
- Technical host names are unique in the engine and limited to
  letters, digits, space, `.`, `-`, `_` — safe in a URL path segment once
  percent-encoded (the portal must use `encodeURIComponent`).
- If this ever has to change, only `mapper.py` and a store migration change;
  nothing past the boundary parses a ref.
