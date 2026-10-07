# Connector payload — what the engine actually pushes

Source of truth for `backend/app/zabbix/connector_schema.py` (Phase 1.2).
Every field below was observed in `lab/ndjson-sink/captured/`; nothing here
comes from the docs alone.

- Engine: Zabbix 7.0.29 (`zabbix/zabbix-server-pgsql:alpine-7.0.29`)
- Captured: 2026-10-08, by `lab/ndjson-sink/sink.py`
- Connectors: `lab-sink-values` (data_type 0), `lab-sink-events` (data_type 1),
  `lab-sink-probes` (data_type 0, tag filter `component=lab`)

Re-capture and re-check this file after any engine upgrade, including patch
releases.

## Transport

| Observed | Value |
|---|---|
| Method | `POST` to the connector URL path (`/values`, `/events`, `/probes`) |
| `Content-Type` | `application/x-ndjson` |
| `Authorization` | `Bearer <token>` (connector `authtype` 5) |
| Body | one JSON object per line; one batch had 1–4 lines in this lab |
| Expected reply | any 2xx; the sink answers `200` with an empty body |

## Value line (data_type 0)

| Field | JSON type | Example | Notes |
|---|---|---|---|
| `host` | object | `{"host":"Zabbix server","name":"Zabbix server"}` | `host` = technical name, `name` = visible name |
| `groups` | array of string | `["Zabbix servers"]` | host group **names**, not IDs |
| `item_tags` | array of `{tag, value}` | `[{"tag":"component","value":"system"}]` | same tag may repeat with different values |
| `itemid` | integer | `46315` | JSON number, not string (the JSON-RPC API returns IDs as strings) |
| `name` | string | `"Number of values synchronized with the database per second"` | item name, macros resolved |
| `clock` | integer | `1791395275` | Unix seconds |
| `ns` | integer | `434012220` | nanoseconds within `clock` |
| `value` | number or string | see per-type table | shape depends on `type` |
| `type` | integer | `0` | the item's **value_type** (not the item type) |

Not present: item key, units, hostid. Units and key must be looked up over
the JSON-RPC API by `itemid` (cache it — `services/` must not call per line).

### Per value_type

| `type` | value_type | `value` JSON type | Extra fields | Captured in |
|---|---|---|---|---|
| 0 | numeric float | number — **may be a JSON integer** (11 of 23 float lines were `0`, not `0.0`) | — | `values/0001.ndjson` |
| 1 | character | string | — | `probes/0001.ndjson` line 1 |
| 2 | log | string | `timestamp` (int), `source` (string), `severity` (int), `eventid` (int) | `probes/0001.ndjson` line 2 |
| 3 | numeric unsigned | integer | — | `values/0006.ndjson`, `probes/0001.ndjson` line 4 |
| 4 | text | string, may contain `\n` | — | `probes/0001.ndjson` line 3 |

The log line's `eventid` is the **log record's** event ID (e.g. Windows event
log), unrelated to the event stream's `eventid`. Name it differently in our
schema.

Not yet observed: unsigned values above 2^53 (none in this lab — must be
checked against a real 64-bit counter such as `ifHCInOctets` before Phase 2),
and value_type 5 (binary).

### Real lines

```json
{"host":{"host":"Zabbix server","name":"Zabbix server"},"groups":["Zabbix servers"],"item_tags":[{"tag":"component","value":"system"},{"tag":"component","value":"nvps"}],"itemid":46315,"name":"Number of values synchronized with the database per second","clock":1791395275,"ns":434012220,"value":1.0822050843726692,"type":0}
{"host":{"host":"Zabbix server","name":"Zabbix server"},"groups":["Zabbix servers"],"item_tags":[{"tag":"component","value":"lab"}],"itemid":50741,"name":"Lab value probe (char)","clock":1791395426,"ns":705405201,"value":"probe-char","type":1}
{"host":{"host":"Zabbix server","name":"Zabbix server"},"groups":["Zabbix servers"],"item_tags":[{"tag":"component","value":"lab"}],"itemid":50742,"name":"Lab value probe (log)","clock":1791395426,"ns":705405202,"timestamp":0,"source":"","severity":0,"eventid":0,"value":"probe log line","type":2}
{"host":{"host":"Zabbix server","name":"Zabbix server"},"groups":["Zabbix servers"],"item_tags":[{"tag":"component","value":"lab"}],"itemid":50740,"name":"Lab event probe","clock":1791395426,"ns":705405204,"value":0,"type":3}
{"host":{"host":"Zabbix server","name":"Zabbix server"},"groups":["Zabbix servers"],"item_tags":[{"tag":"component","value":"lab"}],"itemid":50743,"name":"Lab value probe (text)","clock":1791395426,"ns":705405203,"value":"probe text\nsecond line","type":4}
```

## Event line (data_type 1)

Problem and recovery lines have **different shapes**.

### Problem (`value` = 1)

| Field | JSON type | Example | Notes |
|---|---|---|---|
| `clock` | integer | `1791395301` | Unix seconds |
| `ns` | integer | `288186659` | |
| `value` | integer | `1` | 1 = PROBLEM |
| `eventid` | integer | `20` | |
| `name` | string | `"Lab: event probe is 1"` | trigger name, macros resolved at event time |
| `severity` | integer | `2` | trigger priority (2 = Warning) |
| `hosts` | array of `{host, name}` | `[{"host":"Zabbix server","name":"Zabbix server"}]` | array — a trigger can span hosts |
| `groups` | array of string | `["Zabbix servers"]` | |
| `tags` | array of `{tag, value}` | `[{"tag":"scope","value":"lab"},{"tag":"component","value":"lab"}]` | trigger tags **plus inherited item tags** |

### Recovery (`value` = 0)

| Field | JSON type | Example | Notes |
|---|---|---|---|
| `clock` | integer | `1791395313` | |
| `ns` | integer | `500862698` | |
| `value` | integer | `0` | 0 = OK |
| `eventid` | integer | `21` | the recovery event's own ID |
| `p_eventid` | integer | `20` | **links back to the problem's `eventid`** |

A recovery line carries no name, severity, hosts, groups or tags. To show
"resolved" on a problem, match `p_eventid` against the stored problem; the
store must keep the problem row to resolve it.

### Real lines

```json
{"clock":1791395301,"ns":288186659,"value":1,"eventid":20,"name":"Lab: event probe is 1","severity":2,"hosts":[{"host":"Zabbix server","name":"Zabbix server"}],"groups":["Zabbix servers"],"tags":[{"tag":"scope","value":"lab"},{"tag":"component","value":"lab"}]}
{"clock":1791395313,"ns":500862698,"value":0,"eventid":21,"p_eventid":20}
```

## Consequences for Phase 1

- Parse with `extra="ignore"`; fields may be added in patch releases.
- Float `value` must accept JSON integers.
- Event schema is a union keyed on `value` (1 → problem, 0 → recovery).
- Engine IDs (`itemid`, `eventid`, `p_eventid`) and `clock`/`ns` stop at
  `zabbix/mapper.py`; past it they are `device_ref` / `problem_ref` and a
  timezone-aware `datetime` (CLAUDE.md §4).
