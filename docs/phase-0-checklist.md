# Phase 0 checklist — engine facts verified on our own instance

Re-run this whole file after **any** engine image change, including a patch
release, and record the new results here before starting the next phase.

- Run date: **2026-10-08**
- Engine: `zabbix/zabbix-server-pgsql:alpine-7.0.29`,
  `zabbix/zabbix-web-nginx-pgsql:alpine-7.0.29`,
  `timescale/timescaledb:2.28.3-pg16` (PostgreSQL 16.14)
- Commands assume Git Bash at the repo root, with `ENGINE_TOKEN` loaded:
  `ENGINE_TOKEN=$(grep '^ENGINE_TOKEN=' backend/.env | cut -d= -f2 | tr -d '\r')`

## Section A — Re-verify CLAUDE.md §7 (rebuild plan, Appendix A)

| # | Check | Result | Pass |
|---|---|---|---|
| A.1 | License | `zabbix_server (Zabbix) 7.0.29` … `License AGPLv3: GNU Affero General Public License version 3` | ✅ |
| A.2 | TimescaleDB version | `extversion` = `2.28.3`; server log `TimescaleDB version 2.28.3 is valid`; no `unsupported` | ✅ |
| A.3 | `item.get` returns `lastvalue` | keys include `lastvalue`, `lastclock`, `lastns`, `prevvalue` — full run in Section B | ✅ |
| A.4 | Connector workers | `connector manager #1`, `connector worker #1`, `connector worker #2` (= `ZBX_STARTCONNECTORS` 2) | ✅ |
| A.5 | API client smoke test | `version: 7.0.29`, `hosts: ['Zabbix server']`, bad token rejected with `Not authorized.` | ✅ |

```bash
# A.1
docker run --rm zabbix/zabbix-server-pgsql:alpine-7.0.29 zabbix_server -V

# A.2
docker compose -f engine/docker-compose.yml exec -T db psql -U zabbix -d zabbix \
  -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"
docker compose -f engine/docker-compose.yml logs zabbix-server | grep -i timescale

# A.4
docker compose -f engine/docker-compose.yml top zabbix-server | grep -i connector

# A.5
cd backend && .venv/Scripts/python -m app.zabbix.smoke
```

## Section B — Does `item.get` return `lastvalue`?

**Yes, on 7.0.29.** Filtered to a real, polled item (`lab.event.probe` on
host `Zabbix server`) so an un-polled template item cannot give a false
"empty" answer:

```bash
curl -s -X POST http://127.0.0.1:8080/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' \
  -H "Authorization: Bearer $ENGINE_TOKEN" \
  -d '{"jsonrpc":"2.0","method":"item.get","params":{"limit":1,"output":"extend","filter":{"key_":"lab.event.probe"}},"id":1}' \
  | python -c "import sys,json; r=json.load(sys.stdin)['result'][0]; print(sorted(r)); print({k:r[k] for k in ('lastvalue','lastclock','prevvalue')})"
```

Got: key list contains `lastclock`, `lastns`, `lastvalue`, `prevvalue`;
values `{'lastvalue': '0', 'lastclock': '1791395426', 'prevvalue': '0'}`.

This does not change where tiles read from — that is decided in
`docs/decisions/0005-latest-value-source.md` (our store, not `item.get`).

## Section C — Connector push path (rebuild plan 0.5)

| Check | Result | Pass |
|---|---|---|
| Sink receives values | `[values] batch 1: 4 lines, 1156 bytes, Content-Type=application/x-ndjson` | ✅ |
| Connector settings as read back by `connector.get` | `data_type` 0/1, `authtype` 5, `protocol` 0, `status` **1** (= enabled for connectors), `max_attempts` 1 | ✅ |
| Payload captured | `lab/ndjson-sink/captured/values/0001–0020.ndjson` | ✅ |

## Section D — Event probe (rebuild plan 0.6)

| Check | Result | Pass |
|---|---|---|
| Problem event | `[events] batch 1`, `"value":1,"eventid":20` | ✅ |
| Recovery event | `[events] batch 2`, `"value":0,"eventid":21,"p_eventid":20` | ✅ |

Probe objects kept in the engine on purpose (used again in Phase 1 for
`hooks.py` and SSE):

| Object | Key / name | ID on this instance |
|---|---|---|
| Item (trapper, unsigned) | `lab.event.probe` | 50740 |
| Trigger (Warning) | `Lab: event probe is {ITEM.LASTVALUE}` | 25224 |
| Items (trapper, char/log/text) | `lab.value.char`, `lab.value.log`, `lab.value.text` | 50741–50743 |
| Connector | `lab-sink-values` / `lab-sink-events` / `lab-sink-probes` (tag `component=lab`) | 1 / 2 / 3 |

Fire a problem and its recovery again:

```bash
api() { curl -s -X POST http://127.0.0.1:8080/api_jsonrpc.php \
  -H 'Content-Type: application/json-rpc' -H "Authorization: Bearer $ENGINE_TOKEN" -d "$1"; echo; }
api '{"jsonrpc":"2.0","method":"history.push","params":[{"host":"Zabbix server","key":"lab.event.probe","value":"1"}],"id":1}'
api '{"jsonrpc":"2.0","method":"history.push","params":[{"host":"Zabbix server","key":"lab.event.probe","value":"0"}],"id":2}'
```

Field-by-field results are in `docs/connector-payload.md`.

## Open items found during Phase 0

- Unsigned values above 2^53 not yet observed — check with a real
  `ifHCInOctets` item before Phase 2 (JSON number precision).
- The sink keeps only the first 20 batches per path (`SINK_KEEP`).
  Restarting the sink resets its counter and overwrites `0001.ndjson` onward —
  move `captured/` aside first.
