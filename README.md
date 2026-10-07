# NetWatch 

ระบบ network monitoring — dashboard, กราฟ, รายการ problem และการแจ้งเตือน

## โครงการ

NetWatch แบ่งเป็นสองชั้น:

- **Product ของเรา** — backend (FastAPI) และ frontend (React) ที่เขียนเองทั้งหมด
  เป็นสิ่งที่ลูกค้าเห็นและใช้งาน
- **Monitoring engine** — Zabbix 7.0 ทำงานอยู่ข้างใต้ ทำหน้าที่ poll อุปกรณ์ด้วย
  SNMP, คำนวณ trigger และสร้าง event โดยลูกค้าไม่เห็น

ทำไมแยกแบบนี้:

| เหตุผล | อธิบาย |
|---|---|
| **License** | Zabbix 7.0 เป็น AGPLv3 เราจึงใช้ official Docker image แบบไม่แก้ และคุยกับมันผ่าน HTTP API อย่างเดียว โค้ดของเราจึงปิด source ได้ |
| **เปลี่ยน engine ได้** | ส่วนที่รู้จัก Zabbix อยู่ในโฟลเดอร์เดียว (`backend/app/zabbix/`) ถ้าเปลี่ยน engine หรือ API เปลี่ยน แก้แค่ตรงนั้น |
| **ประสิทธิภาพ** | API ของ Zabbix ออกแบบมาเพื่อ configuration ไม่ใช่สำหรับดึงข้อมูลทำกราฟจำนวนมาก เราจึงเก็บข้อมูลเองใน store ของเรา |

Stack: **Zabbix 7.0 · PostgreSQL + TimescaleDB · Redis · FastAPI · React**

## การทำงาน

```
 Cisco / Aruba ◄── SNMPv3 poll ── Zabbix server ──► DB ของ Zabbix (TimescaleDB)
                                      │                        ▲
                                      │                  Zabbix web + API
                                      │                        ▲
                       ② PUSH: Connector              ① PULL: JSON-RPC API
                       (ทุกค่า + ทุก event)            (configuration)
                                      │                        │
                                      ▼                        │
                 ┌──────────────── backend ของเรา ─────────────┴─────┐
                 │  รับ push ──► store ของเรา (DB แยก) ──► SSE / REST │
                 └──────────────────────────┬────────────────────────┘
                                            ▼
                                   frontend (portal ลูกค้า)
```

### 1. เก็บข้อมูลจากอุปกรณ์

Zabbix server poll อุปกรณ์ทุกตัวด้วย SNMPv3 (เช่นทุก 60 วินาทีสำหรับ throughput)
เก็บค่าลง database ของมันเอง และประเมิน trigger — เมื่อค่าเกินเกณฑ์จะเกิด
**problem event** และเมื่อกลับปกติจะเกิด **recovery event**

### 2. ข้อมูลไหลเข้า backend สองทาง

| ทาง | ทิศทาง | ใช้ทำอะไร |
|---|---|---|
| **① Pull — JSON-RPC API** | backend → Zabbix | configuration เท่านั้น: สร้าง/แก้ host, template, item, trigger และค้นข้อมูลครั้งคราว |
| **② Push — Connector** | Zabbix → backend | **ทุก item value และทุก event** ส่งออกมาทันทีเป็น NDJSON ผ่าน HTTP POST |

กราฟ, ค่าล่าสุดบน dashboard และรายการ problem **มาจากทาง ② เท่านั้น**
ไม่ดึงผ่าน API ของ Zabbix เพราะ API นั้นไม่มีการรวม/ย่อข้อมูลฝั่ง server,
ต้องเรียกทีละ item และทุก call แย่งทรัพยากรกับ UI ของ Zabbix

ตัวอย่างข้อมูลที่ Connector ส่งมา (หนึ่งบรรทัดต่อหนึ่งค่า):

```json
{"host":{"host":"Zabbix server","name":"Zabbix server"},"itemid":46315,"name":"Number of values synchronized with the database per second","clock":1791395275,"ns":434012220,"value":1.08,"type":0}
```

### 3. Backend เก็บและกระจายข้อมูล

backend รับ push แล้วแปลงเป็นข้อมูลของเราเอง เก็บใน **store ของเรา ซึ่งเป็น
database แยก** จากของ Zabbix (backend ไม่อ่านตารางของ Zabbix เลย) จากนั้น
กระจายการเปลี่ยนแปลงไปยัง browser แบบ real-time ด้วย SSE ผ่าน Redis pub/sub

### 4. ส่วนใหญ่ของ backend ไม่รู้ว่า engine คือ Zabbix

```
backend/app/
├── zabbix/      ◄── รู้จัก Zabbix: ID, field, รูปแบบ payload ทั้งหมดอยู่ที่นี่
├── container.py ◄── จุดเดียวที่เสียบ engine เข้ากับส่วนอื่น
├── domain/      ◄─┐
├── services/    ◄─┤ ใช้แค่ข้อมูลของเรา: device_ref, problem_ref, datetime
├── api/         ◄─┤ ห้ามมีคำว่า zabbix หรือ field ของ engine
└── auth/        ◄─┘ (hostid, eventid, itemid, triggerid, clock, ns)
frontend/        ◄── เช่นเดียวกัน
```

- ID ของ engine (เช่น `hostid`) ถูกแปลงเป็น `device_ref` / `problem_ref` ซึ่งเป็น
  string ทึบ ๆ ที่ส่วนอื่นไม่ต้องรู้ว่าข้างในคืออะไร
- เวลาของ engine (`clock` + `ns`) ถูกแปลงเป็น `datetime` ที่มี timezone
- กฎนี้ถูกตรวจอัตโนมัติด้วย `ops/check-boundary.sh` ทุกครั้งที่แก้ไฟล์

### 5. แยกข้อมูลระหว่างลูกค้า (tenant)

- **Admin token** ใช้สำหรับตั้งค่าและ provisioning เท่านั้น
- **ลูกค้าแต่ละรายมี user และ token ของตัวเองใน Zabbix** ที่เห็นเฉพาะ host
  ของตัวเอง ถ้าโค้ดของเรากรองพลาด Zabbix ก็ยังไม่คืนข้อมูลของรายอื่นให้ —
  เป็นการป้องกันชั้นที่สอง

---

กฎและการตัดสินใจทั้งหมดอยู่ใน [`CLAUDE.md`](CLAUDE.md) และ [`docs/`](docs/)
