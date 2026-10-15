# Phase 2 — Checklist: วัตถุประสงค์, ขั้นตอน, ผลตรวจ

ฉบับ 15 ตุลาคม 2026 · คู่กับ `docs/phase-2-guide.html` (โค้ดเต็ม) และ `docs/next-phase-plan.md` (lab บน CML)
คำสั่งทั้งหมดเป็น PowerShell ใช้ helper ใน `$PROFILE`: `nw`, `engine`, `portal-login`, `portal`, `boundary`

## เป้าหมายของ Phase 2

เพิ่มอุปกรณ์เครือข่ายเข้าระบบได้ด้วยการแก้ **`provisioning/inventory.csv` ไฟล์เดียว** แล้วได้ทั้ง:

1. host, template, SNMPv3, host group ของ tenant ใน engine ครบ (ไม่ต้องคลิก UI ทีละตัว)
2. ค่าที่ไหลเข้า store ของเรามี **ชื่อ metric ของเราเอง** (`if_in_bps:Gi1/0/1`) ไม่ใช่ชื่อที่เปลี่ยนตาม description ของพอร์ต
3. ค่าที่ได้ **ตรงกับ CLI จริง** (§9)
4. core ล่ม = **alert ตัวเดียว** ไม่ใช่ N ตัว (dependent trigger, §9)
5. ทุกอย่างรันซ้ำได้ (idempotent) และ config อยู่ใน git เป็น YAML ที่ diff ได้

## ป้ายสถานะ

| ป้าย | ความหมาย |
|---|---|
| ✅ **ผ่าน** | รันและตรวจแล้วกับ engine ของเรา (Zabbix 7.0.29) |
| 🧪 **ผ่าน dry-run** | ตรวจแล้วด้วย host ทดสอบที่ชี้ไป IP ที่ไม่มีอยู่จริง (`192.0.2.x`, TEST-NET) ยังไม่มีอุปกรณ์จริงตอบ |
| 🟢 **ผ่านบน stand-in** | ตรวจแล้วกับ net-snmp container ที่ตอบ SNMPv3 จริง (`lab/snmp-standin/`, ADR 0010) แต่ไม่ใช่ Cisco |
| ⏳ **รอ lab** | ต้องมี switch (CML หรือของจริง) ก่อน |
| 🏢 **รอ site** | ต้องตรวจซ้ำกับอุปกรณ์จริงที่ site (ดูภาคผนวกใน `next-phase-plan.md`) |

## สรุปสถานะ

| ขั้น | งาน | สถานะ |
|---|---|---|
| A0 | Docker / engine ขึ้น | ✅ 15 ต.ค. |
| 2.0 | Global macro SNMPv3 + helper | ✅ 12 ต.ค. |
| 2.1 | Export template upstream | ✅ 12 ต.ค. |
| 2.2 | Clone template + tag `metric` / `netwatch=reachability` | ✅ (import แล้ว, UUID ไม่ชนกับ upstream) |
| 2.3 | Mapper อ่านชื่อ metric จาก tag (ADR 0009) | ✅ unit test + 🧪 end-to-end |
| 2.4 | `catalog.py` / `provision.py` / `verify.py` / `export.py` | 🟢 (แก้ bug 3 จุด ดูด้านล่าง) |
| 2.5 | Core ตัวแรก | 🟢 stand-in · ⏳ Cisco |
| 2.6 | เทียบ throughput | 🟢 stand-in (ต่างกัน < 0.5%) · ⏳ Cisco `show interfaces` |
| 2.7 | Tag filter ของ Connector | ✅ 15 ต.ค. |
| 2.8 | Rollout + dependent trigger | 🟢 stand-in (ล่มจริง 3 ตัว ได้ problem เดียว) · ⏳ Cisco |
| ปิด phase | ชุดตรวจรวม | 🟢 **ปิดแบบมีเงื่อนไข 15 ต.ค.** (ADR 0010) · ⏳ ทำซ้ำบน Cisco |

---

## A0 — Engine ขึ้น ✅

**วัตถุประสงค์:** ทุกขั้นต่อจากนี้คุยกับ engine ผ่าน API ต้องมี engine ที่ทำงานก่อน

**ขั้นตอน**
1. เปิด Docker Desktop (ถ้า error `Virtual Machine Platform not enabled` ดู A0 ใน `next-phase-plan.md`)
2. `docker compose -f engine/docker-compose.yml up -d`
3. `docker compose -f backend/docker-compose.dev.yml up -d`

**ตรวจว่าผ่าน**
```powershell
docker ps --format '{{.Names}} {{.Status}}'
# NetWatch-db / -server / -web / -backend ต้อง (healthy), NetWatch-redis ต้อง Up
engine apiinfo.version
# 7.0.29
```

**ผล 15 ต.ค.:** Docker 29.7.2, ทั้ง 5 container ขึ้น, API ตอบ `7.0.29`

---

## 2.0 — Global macro SNMPv3 ✅

**วัตถุประสงค์:** รหัส SNMPv3 อยู่ใน engine ที่เดียวเป็น Secret macro (§9: ห้ามอยู่ใน git หรือ env) ทุก host อ้างผ่าน `{$SNMPV3.*}`

**ตรวจว่าผ่าน**
```powershell
engine usermacro.get @{output=@('macro','type'); globalmacro=$true} | ? macro -like '*SNMPV3*'
# {$SNMPV3.USER} type 0 (text) / {$SNMPV3.AUTH} type 1 (secret) / {$SNMPV3.PRIV} type 1 (secret)
```

**ข้อผิดพลาดที่พบบ่อย:** ตั้ง AUTH/PRIV เป็น type 0 แล้วรหัสจะโผล่ใน `configuration.export` ของ host

---

## 2.1 — Export template upstream ✅

**วัตถุประสงค์:** เก็บ template ต้นฉบับไว้ใน `templates/upstream/` แบบ read-only เพื่อ diff กับ clone ของเราเวลา Zabbix ออก version ใหม่

**ตรวจว่าผ่าน:** มี `templates/upstream/cisco-ios-by-snmp.yaml` และ `icmp-ping.yaml` และไม่มีใครแก้ (`.claude/settings.json` deny การ Edit/Write ไว้แล้ว)

---

## 2.2 — Clone template + tag ✅

**วัตถุประสงค์:**
- ไม่แก้ template ต้นฉบับ (§9 "clone before editing")
- ใส่ item tag `metric` = ชื่อของเรา บน item ที่ต้องการให้ไหลเข้า store
- ใส่ trigger tag `netwatch=reachability` บน trigger ICMP ตัวเดียวต่อ template เพื่อให้ `provision.py` หาเจอและผูก dependency ได้

**ตรวจว่าผ่าน**
```powershell
engine template.get @{output=@('host'); search=@{host='NetWatch '}; startSearch=$true} | % host
# NetWatch Cisco IOS by SNMP
# NetWatch ICMP Ping
```

**ผล 15 ต.ค.:** ทั้งสองอยู่ใน engine แล้ว UUID ใน clone ไม่ซ้ำกับ upstream เลย (0/85 และ 0/9) จึงไม่มีทาง import ทับต้นฉบับ ใน Cisco clone มี ICMP item 3 ตัว (`icmp_ping`, `icmp_loss`, `icmp_rtt`) และ trigger `No SNMP data collection` depends on `Unavailable by ICMP ping` ของ host เดียวกัน

**ข้อผิดพลาดที่พบบ่อย:** ใช้ `{#IFALIAS}` (description ของพอร์ต) ใน tag `metric` ทำให้ชื่อ metric เปลี่ยนเมื่อมีคนแก้ description ต้องใช้ `{#IFNAME}` เท่านั้น

---

## 2.3 — Mapper อ่านชื่อ metric จาก tag ✅

**วัตถุประสงค์:** ชื่อ metric ใน store ต้องคงที่ (ADR 0009) payload ของ Connector ไม่มี item key จึงใช้ tag `metric` แทน และ ingest ยังไม่ต้องเรียก API เลยสักครั้ง

**ไฟล์:** `backend/app/zabbix/mapper.py` (`metric_name()`), `backend/tests/test_mapper_adapter.py`

**ตรวจว่าผ่าน**
```powershell
cd backend; .venv\Scripts\python -m pytest -q; cd ..
# 79 passed, 8 skipped
boundary
# check-boundary: OK
```

**ผล end-to-end 15 ต.ค. (dry-run):** store ได้ค่าชื่อ `icmp_ping`, `icmp_loss`, `icmp_rtt` ของ host ทดสอบ ไม่ใช่ชื่อที่แสดงอย่าง `ICMP ping`

---

## 2.4 — Provisioning scripts 🧪

**วัตถุประสงค์:**

| ไฟล์ | หน้าที่ |
|---|---|
| `provisioning/inventory.csv` | แหล่งความจริงเดียวของรายการอุปกรณ์ ไม่มีรหัสผ่าน |
| `provisioning/catalog.py` | role → template, interface, SNMP details; tenant; ตรวจ CSV |
| `provisioning/provision.py` | ดัน CSV เข้า engine + store แบบ idempotent แล้วตรวจ ADR 0004 |
| `provisioning/verify.py` | ตรวจแบบอ่านอย่างเดียวว่า engine ตรงกับ CSV และ poll ได้จริง |
| `provisioning/export.py` | export template ของเราและ host เป็น YAML ลง git |

**สิ่งที่ `provision.py` ทำ ตามลำดับ**
1. import `templates/netwatch/templates/*.yaml` เฉพาะที่ต่าง (`configuration.importcompare`)
2. สร้าง host group `tenant/<tenant>/<site>` (group = ขอบเขต tenant ตาม ADR 0004)
3. สร้าง/แก้ host: ชื่อ, group, tag `role`/`site`/`model`, template, interface
4. ผูก dependency: reachability trigger ของลูก depends on ของ `parent`
5. สร้าง user group (read-only บน group ของตัวเอง) + user + API token ต่อ tenant แล้วเก็บ token แบบเข้ารหัสใน store ของเรา
6. ตรวจ ADR 0004: token ของแต่ละ tenant ต้องเห็น host ของตัวเองครบ และไม่เห็นของคนอื่น

**Bug ที่แก้ 15 ต.ค.**

| Bug | อาการ | แก้ |
|---|---|---|
| `inventory.csv` บรรทัดตัวอย่างอยู่เหนือ header | พอลบ `# ` ตาม guide แล้ว CSV อ่านบรรทัด CORE เป็น header → `TypeError: unexpected keyword argument 'CORE-SW-01'` | ย้ายบรรทัดตัวอย่างไปไว้ใต้ header |
| `trigger.adddependencies` ไม่มีใน 7.0 | `[-32601] Method not found` dependency ไม่ถูกสร้างเลย แต่ script ยัง exit 0 | ใช้ `trigger.update` + `dependencies` (รวมของเดิมไว้) ใช้ได้กับ trigger ที่มาจาก template; ทุกบรรทัด `!` ทำให้ exit 1 |
| `IMPORT_RULES` ไม่มี `deleteMissing` | ลบ item ออกจาก clone YAML แล้ว engine ไม่ลบตาม | items/triggers/discoveryRules/graphs/valueMaps/templateDashboards ใช้ `deleteMissing` (YAML ใน git เป็นแหล่งความจริง) รันซ้ำแล้วยัง `0 changes` |

**ผล dry-run 15 ต.ค.** (inventory ชั่วคราว: TEST-CORE → TEST-ACC → TEST-AP บน `192.0.2.x`)
```
run 1:  ~ host group tenant/acme-hq/HQ / ~ host TEST-* created x3 / ~ user group / ~ user / ~ new read token
        ADR 0004 check, tenant acme-hq: PASS
run 2:  ~ dependency TEST-ACC -> TEST-CORE / ~ dependency TEST-AP -> TEST-ACC      (หลังแก้ bug)
run 3:  0 changes                                                                   (idempotent)
verify: global macros PASS / TEST-CORE FAIL (SNMP not available) / TEST-ACC FAIL / TEST-AP PASS / stray hosts PASS
```
`verify` FAIL ที่ CORE/ACC เป็นผลที่ถูกต้อง เพราะ IP ไม่มีอยู่จริง แปลว่า verify จับปัญหา SNMP ได้

**ข้อผิดพลาดที่พบบ่อย**
- เพิ่มอุปกรณ์เหนือบรรทัด header ใน CSV
- เปลี่ยน `technical_name` = ได้ device ใหม่ ประวัติเดิมขาด (ADR 0006) ให้แก้ `display_name` แทน
- เห็น `!` แล้วปล่อยผ่าน: ตอนนี้ script exit 1 ให้แก้จนไม่มี `!`

---

## Stand-in — ใช้แทน switch จนกว่าจะมี CML 🟢

**วัตถุประสงค์:** ทดสอบทุกอย่างใน 2.5–2.8 ที่ไม่ขึ้นกับ Cisco ให้ผ่านกับอุปกรณ์ที่ตอบ SNMPv3 จริง เพื่อปิด Phase 2 และเริ่ม Phase 3 ได้ (ADR 0010) โดยไม่ปนกับ inventory จริง

**ส่วนประกอบ**

| ไฟล์ | หน้าที่ |
|---|---|
| `lab/snmp-standin/Dockerfile`, `entrypoint.sh` | Alpine + net-snmp: SNMPv3 authPriv (SHA/AES128) อย่างเดียว + iperf3 server |
| `lab/snmp-standin/docker-compose.yml` | LAB-CORE `172.18.10.1`, LAB-ACC `.10.11`, LAB-AP `.10.21` บน network `netwatch-engine` |
| `lab/snmp-standin/.env` | passphrase สุ่มของ lab (gitignored ไม่ใช่รหัสของ switch จริง) |
| `provisioning/lab-standin.csv` | inventory ของ lab เลือกด้วย `NETWATCH_INVENTORY` |
| `lab/snmp-standin/standin.ps1` | คำสั่งรวม: `up`, `provision`, `macros`, `verify`, `down` |

**ขั้นตอน**
```powershell
.\lab\snmp-standin\standin.ps1 up          # สร้าง .env (ครั้งแรก) + container 3 ตัว
.\lab\snmp-standin\standin.ps1 provision   # provision.py กับ lab-standin.csv
.\lab\snmp-standin\standin.ps1 provision   # ต้อง 0 changes
.\lab\snmp-standin\standin.ps1 macros      # passphrase ของ lab เป็น host secret macro, รอ SNMP available แล้วสั่ง LLD
.\lab\snmp-standin\standin.ps1 verify      # หลัง LLD ประมาณ 1–2 นาที
.\lab\snmp-standin\standin.ps1 down        # เลิกใช้: ลบ host LAB-*, ข้อมูลใน store และ container
```

**ตรวจว่าผ่าน** (ผลที่คาด):
```
global macros    PASS
LAB-CORE         FAIL  (12 metric items)
    - unsupported: Operating system / Hardware model name / Hardware serial number   <- 3 ตัวนี้เท่านั้น (Cisco MIB)
LAB-ACC          FAIL  (12 metric items)   <- 3 ตัวเดียวกัน
LAB-AP           PASS  (3 metric items)
stray hosts      PASS
```
ห้ามมีบรรทัด `SNMP interface not available` ถ้ามีแปลว่า `.env` ไม่ตรงกับ host macro ให้รัน `macros` ใหม่

**ข้อผิดพลาดที่พบบ่อย**
- รัน `nw provisioning.export` ขณะใช้ lab inventory: host LAB-* จะถูก export ลง `templates/netwatch/hosts/` (`standin.ps1` จึงไม่มีคำสั่ง export)
- รัน `nw provisioning.verify` (inventory จริง) ขณะ stand-in ยังอยู่: ขึ้น `stray hosts FAIL LAB-…` ซึ่งถูกต้อง ให้ `down` ก่อนตรวจของจริง
- เอา passphrase ของ lab ไปตั้งที่ global macro: switch จริงจะใช้ไม่ได้ ของ lab ต้องอยู่ที่ host macro เท่านั้น
- สั่ง LLD ก่อน SNMP กลับมา available: engine ทิ้งคำสั่ง "check now" แล้ว LLD จะรอ 1 ชั่วโมง (`macros` รอให้แล้ว)

---

## 2.5 — Core switch ตัวแรก 🟢 stand-in · ⏳ Cisco

**วัตถุประสงค์:** poll Cisco ตัวจริงด้วย SNMPv3 **authPriv** ให้ได้ 1 ตัวก่อน (§9 "one device first") เพื่อแยกปัญหา config ของ switch ออกจากปัญหาของ script

**ขั้นตอน**
1. Config บน switch (ดู `phase-2-guide.html` หัวข้อ 8, หรือ A3 ใน `next-phase-plan.md` ถ้าเป็น CML):
   ACL `NETWATCH-SNMP` (permit **IP ของเครื่อง Windows** ที่รัน Docker) → view → group `v3 priv` → user `auth sha … priv aes 128 …` → `snmp-server ifindex persist` → `load-interval 30` บนพอร์ตที่จะเทียบ
2. ทดสอบจาก network ของ engine ก่อนเพิ่ม host:
   ```powershell
   docker run --rm -it --network netwatch-engine alpine sh -c "apk add -q net-snmp-tools && snmpget -v3 -l authPriv -u netwatch-poll -a SHA -A '<AUTH>' -x AES -X '<PRIV>' <IP> 1.3.6.1.2.1.1.5.0"
   # SNMPv2-MIB::sysName.0 = STRING: CORE-SW-01
   ```
3. ดูชื่อพอร์ตจริงที่จะกลายเป็นชื่อ metric:
   ```powershell
   docker run --rm -it --network netwatch-engine alpine sh -c "apk add -q net-snmp-tools && snmpwalk -v3 -l authPriv -u netwatch-poll -a SHA -A '<AUTH>' -x AES -X '<PRIV>' <IP> 1.3.6.1.2.1.31.1.1.1.1"
   # IF-MIB::ifName.x = STRING: Gi1/0/1   (lab CML: Gi0/1)
   ```
4. ใน `inventory.csv` ใต้ header: `CORE-SW-01,Core Switch 01,core,acme-hq,HQ,<IP>,<model>,`
5. `nw provisioning.provision` สองรอบ: รอบสองต้อง `0 changes`
6. UI → host CORE-SW-01 → Discovery rules → **Execute now** ที่ "Network interfaces discovery" รอ 2–3 นาที
7. `nw provisioning.verify` แล้ว `nw provisioning.export`

**ตรวจว่าผ่าน**
```powershell
nw provisioning.verify
# CORE-SW-01   PASS  (xx metric items)
# verify: PASS
```

**ข้อผิดพลาดที่พบบ่อย:** ACL ใส่ IP ของ container แทน IP ของเครื่อง Windows / `show running-config` ไม่แสดง snmp user (ใช้ `show snmp user`) / ลดเป็น authNoPriv เพราะ image ไม่มี AES (ผิด §9 ให้เปลี่ยน image)

**ผลบน stand-in 15 ต.ค.**
- `snmpget -l authPriv` ได้ `sysName.0 = LAB-CORE`, ifName = `lo`, `eth0`
- `-l authNoPriv` ได้ `authorizationError` และ priv passphrase ผิดได้ `Timeout` (ปฏิเสธเหมือน switch)
- provision รอบแรกมี changes รอบสอง `0 changes`, ADR 0004 PASS
- verify: SNMP interface available, LLD สร้าง item ของ `eth0`, 12 metric items ต่อ host, unsupported มีแค่ 3 item ที่ใช้ Cisco MIB

---

## 2.6 — เทียบ throughput กับ CLI ⏳

**วัตถุประสงค์:** §9 "never trust the template": ค่าใน portal ต้องตรงกับ `show interfaces` จริง โดยเทียบผ่าน **store ของเรา** (เส้นทางเดียวกับที่ลูกค้าเห็น) ห้ามใช้ `history.get`

**ขั้นตอน**
1. สร้าง portal user (ครั้งเดียว): `docker compose -f backend/docker-compose.dev.yml exec -it backend python -m app.auth.cli add-user somchai acme-hq`
2. `portal-login somchai`
3. ดูค่าจาก store และ CLI ในช่วงเวลาเดียวกัน:
   ```powershell
   portal /api/devices/CORE-SW-01/latest | Where-Object metric -eq 'if_in_bps:Gi1/0/1'
   ```
   ```
   show interfaces GigabitEthernet1/0/1 | include rate
   ```
4. ทำ 3 พอร์ต และต้องมี uplink ที่ traffic สูงอยู่ด้วย (ใน CML ต้องสร้าง load เองด้วย `ping … size 1500 repeat …`)

**ตรวจว่าผ่าน:** ต่างกันไม่เกิน ±10% เมื่อ traffic นิ่ง

**ข้อผิดพลาดที่พบบ่อย**
- ใช้ชื่อพอร์ตเต็ม `GigabitEthernet1/0/1`: `{#IFNAME}` มาจาก ifName ซึ่งบน IOS ปกติเป็นชื่อย่อ ให้ยึดผลจากขั้น 2.5 ข้อ 3
- ใช้ `-like 'if_in_bps:Gi1/0/1*'`: จะจับ `Gi1/0/10`–`19` มาด้วย
- ต่างกัน 8 เท่า: bits/bytes / ค่าติดลบเป็นระยะ: counter 32-bit (ต้องใช้ `ifHCInOctets`)
- ค่าแรกหลัง LLD ยังไม่มา: "Bits received" เป็น change-per-second ต้องรอ walk 2 รอบ (2 นาที)

**ผลบน stand-in 15 ต.ค.** (iperf3 จาก LAB-ACC ไป LAB-CORE ที่ 20 Mbit/s คงที่: `docker exec -d LAB-ACC iperf3 -c 172.18.10.1 -b 20M -t 600`)

| แหล่ง | ค่า |
|---|---|
| iperf3 (อัตราที่ส่งจริง) | 20.000 Mbit/s |
| store `LAB-CORE if_in_bps:eth0` | 20.044 / 20.045 Mbit/s (จุดแรก 20.401) |
| store `LAB-ACC if_out_bps:eth0` (ฝั่งส่ง) | 20.022–20.048 Mbit/s |
| kernel `rx_bytes` delta 60 s บน LAB-CORE | 20.042 Mbit/s |

ต่างกันไม่ถึง 0.5% (จุดแรก 1.8%) และทั้งสองทิศตรงกัน จึงยืนยันได้ว่า multiplier ×8 และ counter 64-bit (`ifHCInOctets`) ถูกต้อง
**ยังต้องทำบน Cisco:** เทียบกับ `show interfaces` จริง 3 พอร์ต รวม uplink

---

## 2.7 — Tag filter ของ Connector ✅

**วัตถุประสงค์:** ให้ engine ส่ง **เฉพาะ item ที่มีชื่อ metric ของเรา** เข้า store แทนที่จะส่งทุก item ของทุกพอร์ต (ลดโหลด ingest และขนาด store) ส่วน event ต้องได้ทุกตัว

**ขั้นตอนที่ทำ 15 ต.ค.** (ผ่าน API เทียบเท่ากับตั้งใน Administration → General → Connectors):
```powershell
$c = engine connector.get @{output=@('connectorid'); filter=@{name=@('acme-values')}}
engine connector.update @{connectorid=$c[0].connectorid; tags_evaltype=0; tags=@(@{tag='metric'; operator=12; value=''})}
```

**ตรวจว่าผ่าน**
```powershell
engine connector.get @{output=@('name','data_type'); selectTags='extend'; filter=@{name=@('acme-values','acme-events')}} | ConvertTo-Json -Depth 5 -Compress
# acme-values: tags [{"tag":"metric","operator":"12","value":""}]
# acme-events: tags []        <- ต้องว่าง
```

**ผล 15 ต.ค.:** หลังตั้ง filter ค่าของ host `Zabbix server` (ไม่มี tag `metric`) หยุดเข้า store ทันที (ค่าสุดท้าย 21:59:58 UTC) ส่วนค่าที่มี tag ของ host ทดสอบยังเข้าปกติ

**ข้อผิดพลาดที่พบบ่อย**
- ตั้ง filter ที่ `acme-events` ด้วย: problem อย่าง `No SNMP data collection` จะไม่ถึง portal
- ผลข้างเคียงที่ต้องรู้: ค่าจาก `Zabbix server` จะไม่เข้า store อีกต่อไป ถ้า Phase 3 ต้องการข้อมูลตัวอย่างก่อนมี switch ให้ใช้ host ทดสอบแบบ dry-run หรือใส่ tag `metric` ให้ item ที่ต้องการ

---

## 2.8 — Rollout + dependent trigger 🟢 stand-in · ⏳ Cisco

**วัตถุประสงค์:**
- เพิ่มอุปกรณ์ที่เหลือด้วยการแก้ CSV อย่างเดียว
- core ล่ม = alert **ตัวเดียว** (§9) โดยใช้ dependency: ACC depends on CORE, AP depends on ACC

**ขั้นตอน (เมื่อมี lab)**
1. Config SNMP บน ACC ทุกตัวแบบเดียวกับ 2.5
2. เพิ่ม ACC-SW-01, ACC-SW-02, AP-01 ลงใน CSV โดย `parent` ชี้ไปที่ uplink
3. `nw provisioning.provision` (ต้องเห็น `~ dependency …` และไม่มี `!`) → รันซ้ำได้ `0 changes` → `verify` PASS → `export`
4. ทดสอบ: ทำให้ CORE ping ไม่ถึง (CML: Stop node / ของจริง: เปลี่ยน IP ของ interface ใน UI) รอ 6 นาที
5. `portal /api/problems | Select-Object device_ref, title`
6. คืนสภาพ (Start node / `nw provisioning.provision` คืน IP ให้เอง) แล้ว problem ต้อง resolve

**ตรวจว่าผ่าน:** มี problem เดียวคือ `Cisco IOS: Unavailable by ICMP ping` ของ CORE-SW-01 ส่วน ACC/AP ไม่มีทั้ง ICMP และ SNMP problem

**ผล dry-run 15 ต.ค.:** ทั้ง 3 host ทดสอบ ping ไม่ถึงตั้งแต่แรก จึงเป็นสถานการณ์ "core ล่มพร้อมกันทั้งสาย"

| host | dependency | ผล |
|---|---|---|
| TEST-CORE | – | PROBLEM (ถูกต้อง: เป็นต้นเหตุ) |
| TEST-ACC | → TEST-CORE | ไม่ fire เลย (ถูกต้อง) |
| TEST-AP | → TEST-ACC → TEST-CORE | ping ล้มเหลว 4 ครั้งติดกัน แต่ไม่ fire (ถูกต้อง: chain 2 ชั้นทำงาน) |

นอกจากนี้ `No SNMP data collection` ของ TEST-CORE/ACC ก็ไม่ fire (depends on ICMP ของ host ตัวเอง) ใน store จึงมี problem แค่ของ TEST-CORE ตัวเดียว
หมายเหตุ: รอบแรก TEST-AP fire ไปก่อนที่ dependency จะถูกใส่ (ตอนนั้น `provision.py` ยังเรียก `trigger.adddependencies`) จึงลบ host แล้วสร้างใหม่เพื่อทดสอบให้ถูกต้อง

**เก็บกวาดหลัง dry-run:** ลบ host TEST-* ออกจาก engine และลบข้อมูล TEST-* ออกจาก store ของเรา (`metric_points` 117 แถว, `latest_values` 9, `problems` 2) ส่วนที่ยังอยู่และใช้ต่อได้กับของจริงคือ host group `tenant/acme-hq/HQ` (ว่าง), user group/user `netwatch-acme-hq-reader*` และ tenant `acme-hq` ใน store (token ใช้ได้)

**ผลบน stand-in 15 ต.ค.** (ล่มจริงด้วย `docker stop`)
```
22:26:54 stop LAB-CORE
22:29:49 problem ของ LAB-CORE เข้า store แล้ว -> stop LAB-ACC, LAB-AP
22:36:51 หลัง 7 นาที problem ที่เปิดอยู่ใน store:  LAB-CORE | Cisco IOS: Unavailable by ICMP ping   (ตัวเดียว)
         trigger ที่เป็น PROBLEM ใน engine:         LAB-CORE  Cisco IOS: Unavailable by ICMP ping   (ตัวเดียว)
22:36:54 start ทั้งหมด
22:37:35 problem ของ LAB-CORE resolve ใน store
```
ACC (1 ชั้น) และ AP (2 ชั้น) ไม่มี problem เลย และ `No SNMP data collection` ของทุกตัวก็ไม่ fire แม้รอเกิน `{$SNMP.TIMEOUT}` 5 นาที
**ยังต้องทำบน Cisco:** ทดสอบซ้ำบน topology ที่ ACC ต่อผ่าน CORE จริงทาง data plane

**ข้อผิดพลาดที่พบบ่อย**
- ทำให้ ACC ล่มก่อน CORE: ACC fire ก่อน เพราะ dependency มีผลเฉพาะเมื่อ master เป็น PROBLEM อยู่แล้ว
- ลืมคืนสภาพ: `verify` จะ FAIL ที่ SNMP interface
- AP แสดง interface unknown: ปกติ เพราะ agent interface เป็นแค่ที่ใส่ IP สำหรับ ping จนกว่าจะปิด decision #1

---

## ปิด Phase 2 🟢 แบบมีเงื่อนไข (15 ต.ค., ADR 0010)

**ปิดบน stand-in แล้ว:** 2.0–2.4 และ 2.7 ผ่านกับ engine จริง ส่วน 2.5, 2.6, 2.8 ผ่านบน stand-in ตามผลด้านบน และ `pytest` 79 passed, `boundary` OK, `export` unchanged

**ยังต้องทำบน Cisco (CML หรือของจริง) ก่อนใช้งานจริง** แล้วจึงเปลี่ยนป้ายเป็น ✅:

| เรื่อง | ทำไม stand-in ทดสอบไม่ได้ |
|---|---|
| item ที่ใช้ Cisco MIB (CPU, memory, fan/PSU/temp, model, serial, OS) | net-snmp ไม่มี MIB เหล่านี้ |
| รูปแบบ ifName ของ Cisco (`Gi1/0/1`) ในชื่อ metric | stand-in ใช้ `eth0` |
| `show interfaces` เทียบกับ portal 3 พอร์ต | ไม่มี IOS CLI |
| SNMPv3 algorithm ที่ IOS รองรับ, counter ที่ 1G/10G | net-snmp ไม่ใช่ IOS และ data plane ไม่ใช่ switch |
| ACL/NAT ของ site, dependency ที่ ACC ต่อผ่าน CORE จริง | ทุกตัวอยู่บน Docker network เดียวกัน |

**ชุดตรวจรวม (รันอีกครั้งตอนทำบน Cisco)** ใช้ inventory จริง และต้อง `standin.ps1 down` ก่อน:
```powershell
nw provisioning.provision        # 0 changes, ไม่มี !, ทุก tenant PASS
nw provisioning.verify           # verify: PASS
nw provisioning.export           # unchanged ทุกไฟล์
Select-String passphrase templates\netwatch\hosts\*.yaml | ForEach-Object { $_.Line.Trim() } | Sort-Object -Unique
# มีแค่ {$SNMPV3.AUTH} / {$SNMPV3.PRIV}
cd backend; .venv\Scripts\python -m pytest -q; cd ..
boundary                         # check-boundary: OK
```
บวก 2.6 ผ่าน 3 พอร์ต และ 2.8 ผ่านการทดสอบ dependency แล้วติดป้ายผล: **"ผ่านบน lab (CML)"** ส่วนที่ต้องทำซ้ำที่ site ดูภาคผนวกใน `next-phase-plan.md`

**Commit (ทำเอง):** `provisioning/` (รวม `lab-standin.csv`), `templates/upstream/`, `templates/netwatch/`, `lab/snmp-standin/`, `backend/app/zabbix/mapper.py`, `backend/tests/test_mapper_adapter.py`, `docs/decisions/0009-…`, `docs/decisions/0010-…`, `docs/phase-2-checklist.md`, `docs/next-phase-plan.md`, `docs/phase-2-guide.html`
ตรวจก่อน commit: `git status --short --ignored lab` ต้องเห็น `!! lab/snmp-standin/.env` (แปลว่าถูก ignore)

## งานค้างที่เจอระหว่างตรวจ (ไม่บล็อกการปิด Phase 2)

- **Problem ค้างใน store เมื่อลบ host** (ตรวจแล้ว 15 ต.ค.): ลบ host ที่มี problem เปิดอยู่ รอ 60 วินาที แล้ว `problems.resolved_at` ยังว่าง เพราะ engine ไม่ส่ง recovery event ผ่าน Connector problem ใน store ของเราจะค้างตลอดไป ต้องให้ `services/reconcile` เทียบกับ `problem.get` เป็นระยะ (Phase 3/4)
- **CLAUDE.md §6** ยังเขียน `templates/acme/` แต่ repo ใช้ `templates/netwatch/`
- **decision L1** (CML อยู่ที่ไหน) พักไว้ก่อน เมื่อตัดสินใจแล้วให้บันทึกเป็น `docs/decisions/0011-lab-devices-on-cml.md`
