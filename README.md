# NetWatch 

ระบบ network monitoring 

## 1. ภาพรวม: product ของเรา กับ engine ข้างใต้

ลูกค้าเห็น **NetWatch** เป็น product ของเรา — portal, dashboard, กราฟ,
แจ้งเตือน ทั้งหมดเป็นของเราเอง

ข้างใต้ใช้ **Zabbix 7.0** เป็น *monitoring engine* ทำหน้าที่ poll อุปกรณ์ด้วย
SNMP, เก็บค่า, คำนวณ trigger และสร้าง event — แต่ **ลูกค้าไม่เห็น Zabbix**
และโค้ดของเราไม่แตะ Zabbix เลยนอกจากผ่าน HTTP

ทำไมแยกแบบนี้:

| เหตุผล | อธิบาย |
|---|---|
| **License** | Zabbix 7.0 เป็น AGPLv3 ถ้าเราแก้ source หรือเขียนโค้ดที่รันอยู่ใน process ของมัน (เช่น frontend module) เราต้องเปิด source ด้วย เราจึงใช้ **official Docker image แบบไม่แก้** และคุยกับมัน **ผ่าน API อย่างเดียว** ซึ่ง backend/frontend ของเราจึงปิด source ได้ |
| **เปลี่ยน engine ได้** | ถ้าวันหนึ่งต้องเปลี่ยน engine หรือ Zabbix เปลี่ยน API ใน major version ใหม่ ส่วนที่ต้องแก้ควรมีแค่โฟลเดอร์เดียว (`backend/app/zabbix/`) |
| **ประสิทธิภาพ** | UI ของ Zabbix และ API ของมันไม่ได้ออกแบบมาให้เป็น data API สำหรับกราฟจำนวนมาก เราจึงเก็บข้อมูลเองใน store ของเรา (ดูข้อ 3) |

---

## 2. สถาปัตยกรรม

```
                         ┌─────────────────────── engine (Docker network: netwatch-engine) ───────────────────────┐
                         │                                                                                         │
 Cisco / Aruba  ◄─SNMPv3─┤  zabbix-server ───────► db (PostgreSQL 16 + TimescaleDB 2.28.3)                         │
 (poll ทุก 60s)          │   │  poller, trigger,      ▲                                                            │
                         │   │  connector workers     │ อ่าน/เขียน DB เดียวกัน                                     │
                         │   │                        │                                                            │
                         │   │                     zabbix-web (nginx + php-fpm) ── 127.0.0.1:8080/api_jsonrpc.php  │
                         └───┼────────────────────────────────────────────────────────────────┬───────────────────┘
                             │                                                                │
              ② PUSH: Connector                                                   ① PULL: JSON-RPC API
              NDJSON over HTTP POST                                               config / provisioning / lookup
              (ทุก item value + ทุก event)                                         │
                             │                                                                │
                             ▼                                                                ▼
              ┌──────────────────────────────── backend ของเรา (FastAPI) ─────────────────────────────────┐
              │  api/hooks.py ──► zabbix/connector_ingest ──► store ของเรา (DB แยก)       zabbix/client.py   │
              │                                                     │                                       │
              │                                    services/ ◄──────┘── bus (Redis pub/sub) ──► SSE           │
              └──────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                             │ REST + SSE
                                                             ▼
                                                 frontend (React, เขียนเอง)
```

Stack: **Zabbix 7.0.29 · PostgreSQL 16 + TimescaleDB 2.28.3 · Redis · FastAPI · React**

- **Redis เป็นของเราเท่านั้น** — Zabbix ไม่ได้ใช้ ใช้ทำ cache ผลลัพธ์จาก API
  และ pub/sub กระจาย event ไปยัง SSE ข้าม uvicorn worker หลายตัว _(Phase 1)_
- **Polling อย่างเดียว ยังไม่ใช้ SNMP trap** — trap อ้างอิง source IP ของอุปกรณ์
  ซึ่งถูก Docker NAT เปลี่ยนไป ทำให้ match host ไม่ได้

---

## 3. ข้อมูลไหลสองทาง: pull กับ push

นี่คือกฎที่สำคัญที่สุดของโปรเจกต์ (CLAUDE.md §3)

### ① Pull — JSON-RPC API (เรา → Zabbix)

ใช้สำหรับ **configuration** เท่านั้น: สร้าง/แก้ host, template, item, trigger,
ตั้ง connector, ค้นข้อมูลแบบครั้งคราว (เช่น "item นี้ชื่ออะไร หน่วยอะไร")

**ห้ามใช้ `history.get` ทำกราฟหรือ dashboard** เพราะ:

- `history.get` ไม่มี aggregation / downsampling ฝั่ง server
- `limit` ของมันนับรวมทั้งผลลัพธ์ ไม่ใช่ต่อ item — "ค่าล่าสุดของ 200 item"
  จึงต้องเรียก 200 ครั้ง
- ทุก call วิ่งผ่าน container PHP ตัวเดียวกับ UI ของ Zabbix แย่ง worker กัน

`item.get` คืน `lastvalue` ได้จริง (ตรวจแล้วบน 7.0.29) แต่ได้ **ค่าเดียว
ไม่ใช่ series** — เราจึงตัดสินใจไม่ใช้มันทำ tile เลย ดู
[ADR 0005](docs/decisions/0005-latest-value-source.md)

### ② Push — Zabbix Connector (Zabbix → เรา)

Connector เป็น feature ของ Zabbix 7.0 ที่ **ส่งทุก item value และทุก event
ออกมาเองทันที** เป็น NDJSON (หนึ่ง JSON object ต่อบรรทัด) ผ่าน HTTP POST

```
POST /values
Content-Type: application/x-ndjson
Authorization: Bearer <token>

{"host":{"host":"core-sw1","name":"Core Switch 1"},"itemid":46315,"name":"...","clock":1791395275,"ns":434012220,"value":1.08,"type":0, ...}
{"host":{...},"itemid":46316, ...}
```

ข้อมูลที่ใช้ทำกราฟ, tile, problem list, SSE **มาจากทางนี้ทั้งหมด** แล้วเก็บใน
store ของเราเอง ซึ่งเป็น **database แยก** จาก Zabbix — backend ห้ามอ่านตาราง
ของ Zabbix ตรง ๆ เด็ดขาด (schema ของมันเปลี่ยนทุก major version)

สิ่งที่ต้องรู้เกี่ยวกับ Connector (ตรวจแล้วบน instance ของเรา):

- ต้องตั้ง `StartConnectors` (ใน Docker คือ env `ZBX_STARTCONNECTORS`) > 0
  ถ้าเป็น 0 สร้าง connector ได้ แต่ **จะไม่มีอะไรถูกส่งออกเลย**
- หนึ่ง connector ส่งได้ชนิดเดียว: `data_type` 0 = item values, 1 = events
- กรองด้วย tag ได้ (เช่นส่งเฉพาะ item ที่มี tag `component=lab`)
- ใน API ของ connector `status: 1` คือ **enabled** (กลับกับที่หลายคนเดา)
- ความลึกของคิวดูได้จาก internal item `zabbix[connector_queue]`

รูปร่าง payload ทุก field จากของจริง อยู่ใน
[`docs/connector-payload.md`](docs/connector-payload.md)

---

## 4. Boundary: ทำไม backend ส่วนใหญ่ห้ามรู้จัก Zabbix

backend แบ่งเป็นสองฝั่ง:

```
backend/app/
├── zabbix/        ◄── ฝั่ง "engine": รู้จัก Zabbix ได้เต็มที่ (hostid, eventid, clock, ns ...)
├── container.py   ◄── จุดประกอบ (wiring) — เลือกว่าจะเสียบ engine ตัวไหน
│
├── domain/        ◄─┐
├── services/      ◄─┤ ฝั่ง "product": ห้ามมีคำว่า zabbix และห้ามมี field ของ engine
├── api/           ◄─┤ (eventid, hostid, itemid, triggerid, clock, ns)
├── auth/          ◄─┘
frontend/          ◄── ฝั่ง product เช่นกัน
```

### กลไกที่ทำให้แยกได้ _(Phase 1)_

1. **Port** — `domain/ports.py` ประกาศ `MonitoringEnginePort` เป็น
   `typing.Protocol` บอกว่า "engine ต้องทำอะไรได้บ้าง" (เช่น `list_devices`)
   โดยไม่บอกว่าเป็น engine อะไร
2. **Adapter** — `zabbix/adapter.py` implement port นั้นด้วย `client.py`
3. **Mapper** — `zabbix/mapper.py` แปลงข้อมูล Zabbix เป็น domain model:
   - `hostid` → `device_ref`, `eventid` → `problem_ref` (string ทึบ ๆ ที่ฝั่ง
     product ห้ามแกะ)
   - `clock` + `ns` → `datetime` แบบมี timezone
4. **container.py** — ที่เดียวที่ `import` ทั้งสองฝั่งแล้วเสียบเข้าหากัน
   `services/` รับ port เข้ามา ไม่ `import zabbix` เอง

ผลคือ ถ้าเปลี่ยน engine ต้องเขียน `adapter.py` + `mapper.py` ใหม่ ส่วน
`services/`, `api/`, `frontend/` ไม่ต้องแตะ

### ใครคอยบังคับกฎนี้: `ops/check-boundary.sh`

script นี้ `grep` หาคำต้องห้ามในโฟลเดอร์ฝั่ง product ทั้งหมด และรันอัตโนมัติ
ในสองที่:

- **Claude Code hook** — ทุกครั้งที่มีการ Write/Edit ไฟล์ใน repo
  (`.claude/settings.json` → `PostToolUse`)
- **CI** ทุก commit _(ยังไม่ได้ตั้ง — ทำตอนมี GitHub Actions)_

รายละเอียดการจับ (ดูในตัว script):

| หมวด | จับอะไร | ตัวอย่างที่โดน | ตัวอย่างที่ผ่าน |
|---|---|---|---|
| engine name | `zabbix` ทุกตัวพิมพ์ ทุกตำแหน่ง | `ZabbixClient`, `ZABBIX_URL` | — |
| engine id | `eventid/hostid/itemid/triggerid` (+`s`) โดยนับ `_` เป็นตัวคั่น และจับ camelCase | `device_hostid`, `hostids`, `deviceHostId` | `ghostid`, `HostIdentity` |
| engine field | `clock`, `ns` เป็นคำเดี่ยว นับ `_` และ camelCase เป็นตัวคั่น | `clock`, `event_clock`, `clock_ns`, `clockNs` | `clocks`, `clockwise`, `dns`, `namespace` |

Exit code: `0` = ผ่าน, `2` = ผิดกฎ (Claude Code จะส่ง stderr กลับให้ model
เห็นและแก้) — โฟลเดอร์ที่ยังไม่ถูกสร้างจะถูกข้ามไป

```bash
bash ops/check-boundary.sh
# ตอนนี้: check-boundary: no guarded paths exist yet — OK
```

**ถ้าเจอ false positive** ให้เปลี่ยนชื่อในโค้ด ไม่ใช่ผ่อน regex — regex คือ spec

---

## 5. ส่วนประกอบที่มีอยู่แล้ว — ทีละไฟล์

### 5.1 `engine/` — Zabbix + TimescaleDB

`engine/docker-compose.yml` **เขียนเองทั้งไฟล์** (ห้ามดาวน์โหลดจาก
zabbix-docker) มี 3 service:

| Service | Image (pin เต็ม tag) | หน้าที่ | Port |
|---|---|---|---|
| `db` | `timescale/timescaledb:2.28.3-pg16` | PostgreSQL ของ **Zabbix** (ไม่ใช่ store ของเรา) | ไม่เปิด — เข้าได้เฉพาะใน network |
| `zabbix-server` | `zabbix/zabbix-server-pgsql:alpine-7.0.29` | poll อุปกรณ์, ประมวล trigger, สร้าง event, ส่ง Connector | ไม่เปิด |
| `zabbix-web` | `zabbix/zabbix-web-nginx-pgsql:alpine-7.0.29` | Web UI (ใช้ตอน dev) + **JSON-RPC API** | `127.0.0.1:8080` (loopback เท่านั้น) |

จุดที่ควรเข้าใจ:

- **ทำไม pin เป็นคู่** — Zabbix รองรับ TimescaleDB เป็นช่วงที่ขยับตาม patch
  release: 7.0.29 รับได้ถึง 2.28.X, ถ้าจะใช้ 2.29.X ต้อง 7.0.30 ขึ้นไป
  tag แบบ `latest-pg16` จึงอันตราย ดู [ADR 0002](docs/decisions/0002-timescaledb-version-pin.md)
- **`ENABLE_TIMESCALEDB=true`** — แปลงตาราง history/trends เป็น hypertable
  มีผล **ครั้งแรกบน DB ว่างเท่านั้น**
- **`ZBX_STARTCONNECTORS=2`** — เปิด connector worker 2 ตัว (ค่า default ของ
  Zabbix คือ 0 = connector ใช้ไม่ได้)
- **`ZBX_TIMEOUT=10`** — SNMP ข้าม WAN ไป access switch ต้องการมากกว่า default 3s
- **`PHP_TZ`** ต้องตรงกับ timezone ของ backend
- **healthcheck** ทุก service — `zabbix-server` รอให้ `db` healthy ก่อนเริ่ม
- **volume** `netwatch-db-data`, **network** `netwatch-engine` (ตั้งชื่อตายตัว
  เพื่อให้ container อื่น เช่น sink เข้าร่วม network ได้)
- รหัสผ่านอยู่ใน `engine/.env` (ไม่ commit) — แม่แบบคือ `engine/.env.example`
  และค่า `POSTGRES_*` มีผลเฉพาะตอนสร้าง volume ครั้งแรก

### 5.2 `backend/app/config.py` — การตั้งค่า

อ่านค่าจาก environment หรือ `backend/.env` ด้วย `pydantic-settings`

- ชื่อตัวแปรเป็น `ENGINE_URL`, `ENGINE_TOKEN` — **ไม่ใช่ `ZABBIX_*`** เพื่อให้
  ส่วนอื่นของ backend ไม่รู้ว่า engine คืออะไร
- `ENGINE_TOKEN` คือ **admin token สำหรับ provisioning เท่านั้น**
  ([ADR 0004](docs/decisions/0004-multi-tenant-token-strategy.md))
  ไม่ใช่ token ที่ใช้อ่านข้อมูลให้ลูกค้า

### 5.3 `backend/app/zabbix/client.py` — JSON-RPC client

client แบบ async (ใช้ `httpx`) สำหรับทาง ① pull

```python
async with ZabbixClient(settings.engine_url) as client:
    hosts = await client.call("host.get", {"output": ["host"]}, token=admin_token)
```

หลักการออกแบบ:

- **`token` เป็น argument บังคับ ทุก call ไม่มีค่า default** — client ตัวเดียว
  ใช้ทั้ง admin token และ per-tenant token คนเรียกต้องระบุชัดว่าใช้ตัวไหน
  และ `client.py` ไม่ `import config` เลย (กันการเผลอใช้ admin token อ่าน
  ข้อมูลของ tenant)
- `token=None` หมายถึง "method นี้ไม่ต้อง auth" ต้องพูดออกมาตรง ๆ —
  `apiinfo.version` จะ **ปฏิเสธ** request ที่มี header `Authorization`
- ส่ง token ผ่าน header `Authorization: Bearer ...` (วิธีของ 7.0)
- JSON-RPC error (`{"error": {...}}`) ถูกแปลงเป็น `ZabbixAPIError` ที่มี
  `method`, `code`, `message`, `data`
- HTTP error (เช่น 502) ถูกโยนเป็น `httpx.HTTPStatusError`
- รองรับ `transport=` เพื่อใช้ mock transport ตอนเขียน test

### 5.4 `backend/app/zabbix/smoke.py` — smoke test

ตรวจว่า client + token + engine ทำงานด้วยกันได้จริง ทำ 3 อย่าง:
อ่าน version (ไม่ใช้ token), `host.get` ด้วย admin token, และลองใช้ token
ปลอม ซึ่ง **ต้องถูกปฏิเสธ**

```bash
cd backend && .venv/Scripts/python -m app.zabbix.smoke
# version: 7.0.29
# hosts: ['Zabbix server']
# bad token rejected: host.get: [-32602] Invalid params. Not authorized.
```

### 5.5 `lab/ndjson-sink/` — ตัวรับ Connector ชั่วคราว (Phase 0)

**เครื่องมือทดลอง ไม่ใช่โค้ด product** — ใช้พิสูจน์ว่าทาง ② push ทำงานจริง
และเก็บ payload ดิบไว้ให้เขียน schema จากของจริงแทนการเดาจากเอกสาร

`sink.py` เป็น HTTP server ด้วย stdlib ล้วน (container ไม่ต้องติดตั้งอะไร):

1. รับ `POST` ทุก path อ่าน body ทั้งแบบ `Content-Length` และแบบ
   `Transfer-Encoding: chunked`
2. **อ่าน body ให้หมดก่อน** แล้วค่อยเช็ก `Authorization: Bearer` — ถ้าตอบ 401
   ก่อนอ่าน connection แบบ keep-alive จะค้าง
3. เอา path เป็นชื่อโฟลเดอร์ (`/values` → `captured/values/`)
4. นับ batch ต่อ path และเขียนไฟล์ `0001.ndjson`, `0002.ndjson`, ... เฉพาะ
   20 batch แรก (`SINK_KEEP`) ที่เกินจากนั้นแค่ log
5. พิมพ์หนึ่งบรรทัดต่อ batch: `[values] batch 3: 4 lines, 1156 bytes, Content-Type=...`

รันเป็น container ชื่อ `netwatch-sink` ใน network `netwatch-engine` เพื่อให้
`zabbix-server` เรียกด้วยชื่อ `http://netwatch-sink:8099/...` ได้
(ใช้ `localhost` ไม่ได้ — จากใน container ของ server `localhost` คือตัว server เอง)

สิ่งที่ตั้งไว้ใน engine สำหรับ lab (เก็บไว้ใช้ต่อใน Phase 1):

| ชนิด | ชื่อ | หน้าที่ |
|---|---|---|
| Connector | `lab-sink-values` → `/values` | ส่งทุก item value |
| Connector | `lab-sink-events` → `/events` | ส่งทุก event |
| Connector | `lab-sink-probes` → `/probes` | ส่งเฉพาะ item ที่มี tag `component=lab` |
| Item (trapper) | `lab.event.probe` | "ปุ่ม" ทำให้เกิด event: push `1` = problem, `0` = recovery |
| Trigger | `Lab: event probe is {ITEM.LASTVALUE}` | `last(...)>=1`, severity Warning |
| Item (trapper) | `lab.value.char` / `.log` / `.text` | ตัวอย่าง value_type ที่ internal item ไม่มี |

ไฟล์ที่ได้อยู่ใน `captured/` (commit ไว้เป็นหลักฐาน และจะเป็น test fixture
ใน Phase 1.2) ส่วน token อยู่ใน `.sink-token` (**ไม่ commit**)

วิธียิง event ซ้ำ และสถานะการตรวจทั้งหมด อยู่ใน
[`docs/phase-0-checklist.md`](docs/phase-0-checklist.md) Section D

### 5.6 `ops/check-boundary.sh`

อธิบายไว้ใน [ข้อ 4](#ใครคอยบังคับกฎนี้-opscheck-boundarysh) ไฟล์ `.sh` ต้องเป็น
LF เสมอ (`.gitattributes` บังคับไว้) — ถ้าเป็น CRLF bash จะพังด้วย
`$'\r': command not found`

### 5.7 `.claude/settings.json`

ตั้งค่าสำหรับ Claude Code ใน repo นี้:

- **hook** รัน `check-boundary.sh` หลัง Write/Edit ทุกครั้ง
- **deny** `git clone`, `gh repo clone`, ดาวน์โหลดจาก github.com และการแก้
  `templates/upstream/**` — ตามกฎแหล่งที่มาของโค้ด (ข้อ 8)

---

## 6. ส่วนประกอบที่ออกแบบไว้ (Phase 1–4)

ยังไม่มีในโค้ด — แผนเต็มอยู่ใน `docs/rebuild-plan.pdf`

### Phase 1 — Backend core

| ไฟล์ | หน้าที่ |
|---|---|
| `domain/models.py` | `Device(ref, name, kind, site, status)`, `MetricPoint(device_ref, metric, ts, value)`, `Problem(ref, device_ref, severity, title, started_at, resolved_at)` — เวลาเป็น `datetime` มี timezone |
| `domain/enums.py` | `Severity`, `DeviceStatus` ของเราเอง (mapper แปลงจากค่าของ engine) |
| `domain/ports.py` | `MonitoringEnginePort` (Protocol) — config/lookup เท่านั้น **ไม่มี** `get_history` |
| `zabbix/connector_schema.py` | Pydantic model ของ value line / event line จาก payload จริง (`extra="ignore"`) |
| `zabbix/mapper.py` | แปลง engine → domain, สร้าง `device_ref` / `problem_ref` |
| `zabbix/adapter.py` | implement port ด้วย `client.py` |
| `zabbix/connector_ingest.py` | parse NDJSON batch → domain objects |
| `api/hooks.py` | endpoint รับ Connector push — **transport อย่างเดียว** schema อยู่ที่ `connector_schema.py` |
| `store/` | `sqlite_store.py` (demo) + `postgres_store.py` (appliance) — DB แยกจาก Zabbix |
| `bus/` | in-memory + Redis pub/sub สำหรับ SSE |
| `services/` | ingest, inventory, metrics, problems, stream, reconcile |
| `container.py` | ประกอบทุกอย่างเข้าด้วยกัน |

สิ่งที่ payload จริงสอนเรา (สำคัญตอนเขียน schema):

- float อาจมาเป็น JSON integer (`0` ไม่ใช่ `0.0`)
- recovery event มีแค่ `clock, ns, value, eventid, p_eventid` —
  ต้องจับคู่ `p_eventid` กับ problem ที่เก็บไว้
- log item มี field ชื่อ `eventid` ที่ **ไม่ใช่** event ID ของ event stream
- value line ไม่มี item key และหน่วย — ต้อง lookup ด้วย API แล้ว cache

### Phase 2 — Provisioning

`provisioning/` — `inventory.csv` → สร้าง host/template ผ่าน API,
ตรวจ per-tenant token ทุกครั้งที่รัน (PASS/FAIL ต่อ tenant), export template
ของเราลง `templates/acme/`

หลักการ: ทดสอบกับ **อุปกรณ์ตัวเดียวก่อน** แล้วค่อยขยาย, เทียบค่ากับ
**CLI จริงของอุปกรณ์** เสมอ, SNMPv3 authPriv, counter 64-bit (`ifHCInOctets`),
`snmp-server ifindex persist` ก่อน LLD, dependent trigger กัน alert ท่วม
เมื่อ core ล่ม, **clone template ก่อนแก้** ไม่แตะ `templates/upstream/`

### Phase 3 — Frontend

React + Vite + TypeScript **เขียนเองทั้งหมด** (ห้ามคัดลอก UI/CSS ของ Zabbix)
UI kit ต้องเป็น MIT/BSD/Apache, กราฟเป็น SVG เขียนเอง, browser คุยกับ
backend ของเราเท่านั้น ไม่เคยคุยกับ engine ตรง

### Phase 4 — Appliance

`ops/docker-compose.acme.yml` (engine + backend + Redis + reverse proxy TLS),
healthcheck (รวมความลึกคิว Connector), backup/restore, LINE webhook,
runbook และ LICENSES ของ Zabbix พร้อม written offer for source

### การตัดสินใจที่ยังเปิดอยู่

| # | เรื่อง | สถานะ |
|---|---|---|
| 1 | Aruba AOS-8 (SNMP) vs AOS-10 + Central (REST) | **OPEN** — ขึ้นกับสิ่งที่ลูกค้าซื้อ (ขอ PO) |
| 3 | Zabbix proxy ที่ site vs poll ตรง | **OPEN** |
| 2, 4, 5 | TimescaleDB pin, token strategy, ที่มาของ latest value | ตัดสินแล้ว — ดู `docs/decisions/` |

---

## 7. เริ่มต้นใช้งานบนเครื่อง dev

ต้องมี: Docker Desktop, Git Bash, Python 3.12+

```bash
# 1. ตั้งค่า engine
cp engine/.env.example engine/.env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # ใส่เป็น POSTGRES_PASSWORD
docker compose -f engine/docker-compose.yml up -d
docker compose -f engine/docker-compose.yml ps
# expect: db, zabbix-server, zabbix-web — ทั้งหมด (healthy)

# 2. สร้าง API token: เปิด http://127.0.0.1:8080 → Users → API tokens
#    แล้วใส่ใน backend/.env (คัดลอกจาก backend/.env.example)

# 3. backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m app.zabbix.smoke
# expect: version: 7.0.29 / hosts: [...] / bad token rejected: ...

# 4. boundary guard
cd .. && bash ops/check-boundary.sh
# expect: exit 0
```

ข้อผิดพลาดที่พบบ่อย:

- เปลี่ยน `POSTGRES_PASSWORD` ใน `.env` ทีหลัง **ไม่ได้เปลี่ยนรหัสใน DB ที่มีอยู่**
  — ต้องลบ volume `netwatch-db-data` (ข้อมูลหายหมด) หรือเปลี่ยนด้วย `ALTER USER`
- เปลี่ยน image tag ของ Zabbix หรือ TimescaleDB ข้างเดียว → server log
  ขึ้น "unsupported" — ต้องเช็กคู่เวอร์ชันตาม ADR 0002
- หลังอัปเกรด engine ทุกครั้ง (แม้แค่ patch) ให้รัน
  `docs/phase-0-checklist.md` ใหม่ทั้งหมด

---

## 8. License และแหล่งที่มาของโค้ด

- **Zabbix (AGPLv3)** — ใช้ official image ไม่แก้, คุยผ่าน API เท่านั้น,
  **ห้ามเขียน Zabbix frontend module แล้วปิด source** (รันใน process เดียวกัน =
  derivative work) เมื่อส่ง appliance ให้ลูกค้าต้องแนบ LICENSE และ
  written offer for source
- **TimescaleDB Community (TSL)** — ใช้ on-prem ฟรี ห้ามขายต่อเป็น service
- **โค้ดของเรา** — closed-source, repo ต้องเป็น **Private**
- **ห้าม** `git clone` repo อื่นเข้ามา, ห้าม copy โค้ดจาก GitHub/gist/blog,
  ห้ามดาวน์โหลด compose ของ zabbix-docker — ทุกบรรทัดต้องอธิบายได้
- **อนุญาต** official images, เอกสาร zabbix.com, template YAML ทางการ,
  เอกสาร/MIB ของ vendor, และ `pip`/`npm install` สำหรับ dependency

---

## 9. เอกสารอื่น ๆ

| ไฟล์ | เนื้อหา |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | กฎทั้งหมด, ข้อเท็จจริงที่ตรวจแล้ว, การตัดสินใจ — **spec หลัก** |
| `docs/rebuild-plan.pdf` | แผนสร้างใหม่ทีละขั้น Phase 0–4 |
| [`docs/connector-payload.md`](docs/connector-payload.md) | ทุก field ของ payload Connector จากของจริง |
| [`docs/phase-0-checklist.md`](docs/phase-0-checklist.md) | ผลตรวจข้อเท็จจริงของ engine บน instance เรา + วิธีรันซ้ำ |
| [`docs/decisions/`](docs/decisions/) | ADR 0002 (TimescaleDB pin), 0004 (token ต่อ tenant), 0005 (ที่มาของ latest value) |
