# acme-nms

_Rebuild — starting again from scratch, one step at a time, beginning with
`engine/`. The rules and verified facts below are still the specification;
nothing in them has been superseded._

**Status, 2026-10-06.** The whole tree was deleted on purpose so it can be
rebuilt by hand. Only this file and `.claude/` remain. The previous, finished
build (Phase 1, working end to end as of 2026-09-14) is kept untouched at
`../NetWatch-backup-2026-10-06/` — reference only, never copy from it wholesale.
Files listed in §6 do not exist yet unless they have been rebuilt; the
`ops/check-boundary.sh` hook will error until that script is written again.
The old Docker volumes from the previous engine may still exist — remove them
before the first `docker compose up` of the new engine.

---

## 1. Context

We are a network engineering / SI team deploying a network at a customer site
(Cisco core switch, Cisco access switches, Aruba APs) **and** delivering a
monitoring product to that customer.

`acme-nms` is **our** product. Zabbix is the engine underneath it, hidden from
the customer. Our backend and frontend are closed-source; Zabbix is not.

---

## 2. Architecture — decided, do not re-litigate

- **Zabbix 7.0** as the monitoring engine. **Official Docker image only.**
  No source modification, no custom build of Zabbix itself.
- **Our own backend/portal**, talking to Zabbix **only over its HTTP API**
  (JSON-RPC 2.0 — see §3) so our code can stay closed-source.
- **Frontend written by us from scratch.** No Zabbix UI code, CSS, theme, or
  view file is ever copied. UI kit must be MIT/BSD/Apache (MUI, Ant Design,
  shadcn/ui + Tailwind all acceptable).
- Stack: Zabbix 7.0 + TimescaleDB + Redis + FastAPI + React.
- Redis is **ours only** — Zabbix does not use it. Purpose: caching engine API
  responses, and pub/sub fan-out for SSE across uvicorn workers.
- Polling only for now. **No SNMP traps** until explicitly decided
  (source-IP matching breaks behind Docker NAT).

---

## 3. Data path — the rule that overrides convenience

**Zabbix's API is a configuration API, not a data API.** Do not build any
dashboard, graph, or "latest value" view on top of `history.get`. It will not
scale and it is not what that method is for.

| Path | Carries | Lands in |
|---|---|---|
| **JSON-RPC API** (pull) | configuration, provisioning, host/template/trigger/item CRUD, on-demand lookups | `backend/app/zabbix/client.py` |
| **Zabbix Connector** (push, NDJSON over HTTP POST) | **all item values + all events** | `backend/app/api/hooks.py` → our own store |

Why this is not optional:

- **Correction, verified 2026-09-09 against our own running instance (Zabbix
  7.0.29):** `item.get` *does* return `lastvalue`/`lastclock`/`prevvalue` when
  `output` includes them — the line that used to be here ("item.get does not
  return lastvalue") was wrong for this version. See §7 for the evidence and
  the re-verify command. This does **not** overturn the rule above — `item.get`
  still gives only **one value per item, never a series**, so it cannot produce
  a graph, and every call still goes through the frontend PHP container (next
  bullet). Whether it is good enough for a single "latest value" status tile was
  an open decision; it is now **CLOSED — see
  `docs/decisions/0005-latest-value-source.md`**. Latest values come from our
  own store, on the same path as the graphs, so a tile and the chart beneath it
  cannot disagree. `mapper.device_from_api()` deliberately ignores the
  `lastvalue` members even though they are present.
- `history.get` has no server-side aggregation or downsampling, and its `limit`
  applies to the whole result set, **not per item**. "Latest value for 200 items"
  is therefore 200 API calls.
- Every API call goes through the frontend PHP container (`nginx` + `php-fpm`),
  so API load competes directly with UI workers.

Consequences that must hold:

- Graphs, dashboards, and SSE read **only** from our own store. Never `history.get`.
- Our store is a **separate database** (or at minimum a separate schema with its
  own role) from Zabbix's. The backend must never read Zabbix's tables — that
  breaks the API-only rule *and* couples us to a schema that changes every major
  version.
- `api/hooks.py` is a transport shell only. Payload schemas live in
  `backend/app/zabbix/connector_schema.py`.

Connector facts (Zabbix 7.0): streams item values and events; `POST` with
`Content-Type: application/x-ndjson`; configured at *Administration → General →
Connectors* or via the `connector.*` API; needs `StartConnectors` in
`zabbix_server.conf`; supports tag filtering, Bearer auth, up to 100 concurrent
sessions, max 5 retries, 1–60s timeout; queue depth is exposed by the internal
item `zabbix[connector_queue]`.

---

## 4. Boundary rule — hard constraint, enforced in CI

`backend/app/domain/`, `backend/app/services/`, `backend/app/api/`,
`backend/app/auth/`, and `frontend/` must **never** contain:

- the word `zabbix` (any case)
- engine-specific fields: `eventid`, `hostid`, `itemid`, `triggerid`, `clock`, `ns`

**Warn me immediately if a suggestion would break this.**

How the boundary is held:

- `services/` depends on `domain/ports.py::MonitoringEnginePort` (a `Protocol`),
  never on `zabbix/` directly.
- IDs cross the boundary as **opaque strings**: `device_ref`, `problem_ref`.
  Only `zabbix/mapper.py` knows they contain a `hostid` / `eventid`.
- Exactly two paths are exempt and whitelisted:
  `backend/app/zabbix/**` and `backend/app/container.py`.
- Enforced by `ops/check-boundary.sh`, which runs in CI on every commit and as a
  `PostToolUse` hook on every Write/Edit in this repo.

---

## 5. Sources

### Allowed

| Source | Use |
|---|---|
| Official Docker images (`zabbix/*`, `postgres`, `timescale/*`, `redis`) | pull and run as-is, never rebuilt |
| `zabbix.com/documentation` | reading, understanding |
| `zabbix.com/integrations` | downloading official template YAML |
| `configuration.export` from our own running instance | populating `templates/upstream/` |
| Vendor docs (Cisco, HPE/Aruba), MIB files from vendor sites | OID reference |
| `pip install` / `npm install` for **dependencies** | normal dependency use |

### Not allowed

- `git clone` of any repo into this workspace
- Copy-pasting code from repos, gists, or blog posts into our source tree
- Vendoring "reference implementations" then editing them
- Downloading `zabbix-docker` compose files — **we hand-write `engine/docker-compose.yml`**

**If a suggestion would require cloning or copying from GitHub, say so explicitly
and give the hand-written alternative instead.**

Rationale: nothing enters the codebase that we cannot explain line by line; no
license contamination, ever; and writing the compose file and API client by hand
*is* how we learn Zabbix.

---

## 6. Project structure

```
acme-nms/
├── engine/            Zabbix + TimescaleDB compose, hand-written
├── templates/
│   ├── upstream/      exported from Zabbix as-is — READ ONLY, kept for diff
│   ├── acme/          our own hosts, exported by provisioning/export.py
│   └── media/         line_webhook.js
├── provisioning/      inventory.csv, catalog.py, provision.py, verify.py, export.py
├── backend/app/
│   ├── zabbix/        client.py, adapter.py, mapper.py, connector_schema.py,
│   │                  connector_ingest.py
│   ├── domain/        models.py, enums.py, ports.py
│   ├── services/      ingest, inventory, metrics, problems, stream, reconcile
│   ├── store/         sqlite_store.py (demo) + postgres_store.py (appliance)
│   ├── bus/           memory + Redis pub/sub fan-out for SSE
│   ├── api/           endpoints + hooks.py receiving Connector push
│   ├── auth/          user ↔ tenant ↔ host group
│   ├── cache.py       engine API response cache (memory or Redis)
│   ├── config.py      ENGINE_URL / ENGINE_TOKEN (never ZABBIX_*)
│   ├── container.py   the single wiring point
│   └── main.py        ASGI app; also serves the built portal
├── backend/tests/     75 tests, including the boundary rule as a test
├── frontend/          React + Vite, written from scratch, hand-written SVG charts
├── lab/
│   ├── demo/          feeder.py — drives the demo network through the real engine
│   └── ndjson-sink/   Phase-0 receiver + the captured batches
├── ops/               check-boundary, healthcheck, backup, restore,
│                      docker-compose.acme.yml, make-practice-copy.py
└── docs/              architecture, runbook, alert-catalog, demo-script,
                       connector-payload, phase-0-checklist, decisions/
```

---

## 7. Verified facts about Zabbix 7.0 — and how to re-verify

These were checked against upstream docs in Aug 2026. Zabbix changes these
between patch releases, so re-verify against **our own running instance** before
depending on any of them.

**License — Zabbix 7.0 is AGPLv3** (changed from GPLv2 at 7.0). Zabbix's own
announcement states the obligation triggers on *modifying* the software, and
that "application programming interfaces (APIs) are not protected by copyright."
Our design — official image unmodified, API-only, own frontend — is what keeps
us clear. When shipping an appliance to a customer we are *distributing* Zabbix:
keep its LICENSE, do not strip copyright notices, include a written offer for
source. **Never write a Zabbix frontend module and close its source** — that runs
in-process and is a derivative work.

```bash
docker run --rm zabbix/zabbix-server-pgsql:alpine-7.0-latest zabbix_server -V
# expect: copyright line naming GNU Affero General Public License v3
```

**Database support matrix** — PostgreSQL **13.0–18.X**, TimescaleDB
**2.13.0–2.29.X** as a PG extension (the supported ceiling rises per patch
release: 2.15.X from 7.0.1 … 2.29.X from 7.0.30). Pin the **full tag** in
`engine/docker-compose.yml`; `timescale/timescaledb:latest-pg16` resolves to a
version outside the range. TimescaleDB compression lives in Community Edition
(TSL license) — free for our on-prem delivery, only barred from being resold as
TimescaleDB-as-a-service.

```bash
docker compose exec -T db psql -U zabbix -d zabbix \
  -c "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"
docker compose logs zabbix-server | grep -i timescale
# expect: the detected version, and NO line containing "unsupported"
```

**Does `item.get` return `lastvalue`?** — **verified yes**, on this instance,
confirmed 2026-09-09 against Zabbix 7.0.29 (see `docs/phase-0-checklist.md`
Section B for the full run). This doc previously said "believed no" — that was
wrong for this version. Re-run the command below on any other Zabbix version
before trusting the answer either way:

```bash
curl -s -X POST "$ENGINE_URL/api_jsonrpc.php" \
  -H 'Content-Type: application/json-rpc' \
  -H "Authorization: Bearer $ENGINE_TOKEN" \
  -d '{"jsonrpc":"2.0","method":"item.get","params":{"limit":1,"output":"extend"},"id":1}' \
  | jq '.result[0] | keys'
# expect: "lastvalue", "lastclock", "prevvalue" present in the key list.
# Note: an item with no poll yet (or a template-only item, not linked to a
# real host) will still show the "lastvalue" KEY but with "lastclock":"0" and
# an empty/zero value — that is not the same as the key being absent. Filter
# item.get to a real, actively-polled host if the first result looks empty.
```

This does **not** overturn §3's Connector requirement for graphs/history — it
only means the "item.get can't give latest values" reasoning behind that rule
was wrong. Whether `item.get` is good enough for single latest-value dashboard
tiles specifically is a separate, still-open call — see
`docs/phase-0-checklist.md` Section B.

---

## 8. Open decisions — close before the sprint they block

| # | Decision | Blocks | Status |
|---|---|---|---|
| 1 | Aruba **AOS-8** (SNMP to controller) vs **AOS-10 + Central** (REST, OAuth2, rate-limited) | all Aruba templates, `lab/mock-central/`, poll interval design | **OPEN** — determined by the AP model and license the customer already bought, not by us. Ask for their PO. Design `templates/acme/` as master item + dependent items with JSONPath preprocessing so either path works. |
| 2 | TimescaleDB version pin | `engine/docker-compose.yml` | **RESOLVED** — see §7. Pick a full tag inside 2.13.0–2.29.X on PG 13–18 and record it in `docs/decisions/`. |
| 3 | Zabbix proxy on-site vs direct polling | `engine/`, network design | OPEN |
| 4 | Multi-tenant token strategy | `backend/app/zabbix/client.py`, `backend/app/auth/` | **RESOLVED and VERIFIED** — see `docs/decisions/0004-multi-tenant-token-strategy.md`. Admin token for config/provisioning; **per-tenant Zabbix user + API token for the read path**, so Zabbix host-group permissions are a second line of defence. `client.py` takes the token as a parameter — never read it from `config.py`. The ADR's verification procedure is now automated: `provisioning/provision.py` runs it on **every** run and prints PASS/FAIL per tenant. First passed 2026-09-10 (acme-hq sees exactly its 8 hosts, branch-co exactly its 1). |
| 5 | Where a "latest value" comes from | `zabbix/adapter.py`, `store/`, tiles | **RESOLVED** — `docs/decisions/0005-latest-value-source.md`. Our own store, not `item.get`'s `lastvalue`. |
| 6 | What is inside `device_ref` | `zabbix/mapper.py`, store | **RESOLVED** — `docs/decisions/0006-device-ref-is-host-name.md`. Technical host name (the push carries names, not hostids). Host names are permanent IDs: renaming one starts a new device. |
| 7 | Store placement + retention | `store/`, `ops/init-store.sh` | **RESOLVED for Phase 1** — `docs/decisions/0007-store-placement-and-retention.md`. DB `acme` + role `acme_app` in the engine's PG instance, CONNECT on the engine DB revoked; raw points 30 days. Confirm retention with the customer before Phase 4. |
| 8 | Portal login | `auth/`, `api/auth.py` | **RESOLVED for Phase 1** — `docs/decisions/0008-portal-login.md`. Password (scrypt) → HMAC-signed session token in an HttpOnly cookie (or Bearer). No SSO yet. |

---

## 9. Engineering principles

- Test on **one device first**, then roll out to the full set
- Always verify values against **real CLI output** — never trust the template
- SNMPv3 **authPriv**, 64-bit counters (`ifHCInOctets`), 60s poll for throughput
  items; slower intervals are fine for error/discard counters
- Always **clone a template before editing** — never modify `templates/upstream/`
- No credentials in git. DB/API credentials in environment variables; SNMPv3
  credentials via Zabbix Vault macro or Secret text macro (they cannot live in
  env vars — they live in the Zabbix DB)
- `snmp-server ifindex persist` on every Cisco device before any LLD runs
- Dependent triggers so a core failure does not produce N false alerts

---

## 10. How to respond to me

- **Thai**, keeping technical terms in English (SNMP, trigger, OID, poller, LLD…)
- Real, copy-paste-ready code and config — **no pseudo-code**
- **State the file path** from §6 for every piece of code
- Every procedure ends with a **"how to verify it passed"** check with expected output
- Call out **common mistakes** for each step
- If a fact about Zabbix behaviour is version-dependent or I might be
  misremembering it, say so and give me the command to verify it against my own
  running instance
