# 0009 — Metric name comes from the item tag `metric`

- Status: **Accepted**
- Date: 2026-10-14 (Phase 2.3)
- Affects: `backend/app/zabbix/mapper.py` (`metric_name()`),
  `templates/netwatch/templates/*.yaml`, Connector tag filter (Phase 2.7)

## Context

Until now `mapper.metric_from_value()` used the item's display name as the
metric name. The Connector push carries no item key (`docs/connector-payload.md`),
only `itemid`, `name` and `item_tags`. The Cisco template names interface
items `Interface {#IFNAME}({#IFALIAS}): Bits received`, and `{#IFALIAS}` is the
port description on the switch. When someone edits a description, the item
name changes, the metric gets a new name in our store and the graph breaks.
Template upgrades can rename items too.

`itemid` is not an option: it may not cross the boundary (CLAUDE.md §4), and
it changes when a host is deleted and recreated.

phase-1-guide item 15 planned to look up key/units with `item.get` and cache
them by itemid. That puts an API call (or a cache that can go stale) on the
hot ingest path, and ties our metric names to engine item keys.

## Decision

Items we want get an item tag `metric` whose value is **our** name, set in
our template clones (`NetWatch Cisco IOS by SNMP`, `NetWatch ICMP Ping`):
`if_in_bps:{#IFNAME}`, `cpu_util:{#SNMPINDEX}`, `icmp_rtt`, `uptime`, …
LLD macros are resolved by the engine, so the push carries e.g.
`if_in_bps:Gi1/0/1`. `{#IFALIAS}` is never used in the tag.

`mapper.metric_name()` returns that tag's value, falling back to the display
name for items without it (lab probes).

## Consequences

- Metric names survive port-description edits and template renames.
- Ingest still needs zero API calls.
- Names are ours and engine-neutral; nothing past the boundary sees an item key.
- The Connector can filter on the tag (Phase 2.7), so only tagged items are pushed.
- **No units yet**: the push carries none. To be added later (tag or catalog).
- Changing a tag value starts a new series, exactly like renaming a host
  (ADR 0006): treat the values as permanent once data exists.
