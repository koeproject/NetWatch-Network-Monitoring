# แผนงานต่อจากนี้: ปิด Phase 2 ด้วย lab บน CML แล้วไปต่อ Phase 3

ฉบับวันที่ 15 ตุลาคม 2026 · ใช้คู่กับ `docs/rebuild-plan.pdf` และ `docs/phase-2-guide.html`

## สถานะตอนนี้

| ส่วน | สถานะ |
|---|---|
| Phase 0, Phase 1 | เสร็จ (ดู `docs/phase-0-checklist.md`) |
| Phase 2 ขั้น 2.0–2.1 | เสร็จและตรวจแล้ว 12 ต.ค. |
| Phase 2 ขั้น 2.2–2.4 (template clone, mapper อ่าน tag `metric`, ADR 0009, `catalog.py` / `provision.py` / `verify.py` / `export.py`) | เขียนโค้ดเสร็จ 14 ต.ค. แต่ยังไม่ได้รันกับอุปกรณ์จริง |
| Phase 2 ขั้น 2.5–2.8 | **ปิดแบบมีเงื่อนไข 15 ต.ค.** บน net-snmp stand-in (ADR 0010, `docs/phase-2-checklist.md`) ส่วนที่ต้องทำซ้ำบน Cisco คือ Track A ด้านล่าง |
| Docker Desktop | ใช้ได้แล้ว (15 ต.ค.) |

งานต่อไปจึงมี 2 track:

- **Track A:** ใช้ CML จำลอง Cisco แทนของจริง เพื่อปิด 2.5–2.8 (ขั้น A0–A8)
- **Track B:** Phase 3 frontend ทำคู่ขนานได้ เพราะ read API จาก 1.6 คงที่แล้ว (ขั้น B1–B6)

---

## ขั้น A0 — ทำให้ Docker กลับมาทำงาน

**เป้าหมาย:** engine (Zabbix + TimescaleDB) และ backend ต้องขึ้นก่อน งานอื่นทั้งหมดรอขั้นนี้

ให้เปิด PowerShell แบบ **Run as administrator** แล้วรัน:

```powershell
dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
wsl --update
```

จากนั้น restart เครื่อง แล้วเปิด Docker Desktop

**ตรวจว่าผ่าน** (ใช้ PowerShell ธรรมดาที่ root ของ repo):

```powershell
docker info --format '{{.ServerVersion}}'        # ต้องได้เลข version ไม่ใช่ "unable to start"
docker compose -f engine/docker-compose.yml up -d
docker compose -f engine/docker-compose.yml ps   # db, zabbix-server, zabbix-web ต้องเป็น (healthy) ทั้ง 3 ตัว
nw app.zabbix.smoke                              # version: 7.0.29 / bad token rejected
```

**ข้อผิดพลาดที่พบบ่อย**

- ถ้ายังขึ้น `No virtualization available` หลัง reboot ให้เช็กว่า VT-x/AMD-V เปิดอยู่ใน BIOS: `Get-CimInstance Win32_Processor | Select VirtualizationFirmwareEnabled` ต้องได้ `True`
- ห้ามกด "Reset to factory defaults" หรือ "Clean / Purge data" ใน Docker Desktop เพราะ volume ของ engine (DB ของ Zabbix และ store `acme`) จะหายทั้งหมด

---

## ขั้น A1 — ตัดสินใจว่าจะรัน CML ที่ไหน (decision ใหม่ L1)

**CML ไม่ใช่ Docker image** มันเป็น VM (OVA/ISO) ที่ข้างในต้องรัน VM ของ IOSv อีกชั้น จึงต้องใช้ **nested virtualization** ดังนั้นเปิด CML ใน Docker ไม่ได้

| ทางเลือก | ผล |
|---|---|
| **ก. CML อยู่อีกเครื่อง** (PC อีกตัว, server ของ lab, หรือ CML ของมหาวิทยาลัย/บริษัท) **(แนะนำ)** | Docker บนเครื่องนี้ poll ข้าม LAN ได้ตรงๆ และไม่ชนกับ Hyper-V |
| ข. CML ใน VMware Workstation บนเครื่องนี้ | Docker ต้องเปิด Virtual Machine Platform ไว้ แต่พอเปิดแล้ว VMware จะ expose VT-x ให้ guest ไม่ได้ IOSv จึงบูตไม่ขึ้นหรือช้ามาก ส่วนการปิด VMP ก็ทำให้ Docker ใช้ไม่ได้ สรุปคือ **รันพร้อมกันไม่ได้** |
| ค. CML บน Hyper-V | Cisco ไม่ได้รองรับอย่างเป็นทางการ ไม่แนะนำ |

> **อาจไม่ตรงกับ version ที่คุณใช้:** ข้อจำกัดของ VMware + Hyper-V เรื่อง nested VT-x เปลี่ยนไปตาม version ของ VMware และ Windows ถ้าจะลองทางเลือก ข. ให้ตรวจก่อน: เปิด VM settings → Processors แล้วติ๊ก "Virtualize Intel VT-x/EPT" ถ้า VM ไม่ยอมบูตและขึ้นข้อความว่า Hyper-V conflict แปลว่าใช้ไม่ได้

บันทึกการตัดสินใจไว้ใน `docs/decisions/0011-lab-devices-on-cml.md` ให้มีเหตุผล, ทางเลือกที่ไม่เลือก และเขียนไว้ว่า **ผลจาก CML ไม่ได้แทนการตรวจกับอุปกรณ์จริงที่ site** (§9)

---

## ขั้น A2 — Topology ใน CML

**เป้าหมาย:** ได้ topology เล็กที่สุดที่ทดสอบได้ครบทั้ง 2.5 (core ตัวแรก), 2.6 (throughput), 2.8 (dependency)

```
                 [External Connector: bridge → LAN เดียวกับเครื่อง Windows]
                                   │ Gi0/0 (mgmt)
                             CORE-SW-01  (IOSvL2)
                    Gi0/1 ┌──────┴──────┐ Gi0/2
                     ACC-SW-01       ACC-SW-02     (IOSvL2)
                 Gi0/1 │
                     AP-01  (Alpine node แทน AP, ใช้แค่ ICMP)
```

- Management ของทุกตัวอยู่ใน VLAN 1 / SVI ที่ bridge ออก LAN ผ่าน External Connector **โหมด bridge** (ห้ามใช้ NAT เพราะ Zabbix ต้องเข้าถึง IP ของอุปกรณ์ได้ตรงๆ)
- ใช้ subnet เดียวกับเครื่อง Windows เช่น LAN `192.168.1.0/24`: CORE `.201`, ACC-01 `.211`, ACC-02 `.212`, AP-01 `.221` (เลือกเลขที่ DHCP ไม่แจก)

**Config พื้นฐาน** (CORE-SW-01; ACC ใช้แบบเดียวกันแต่เปลี่ยน hostname/IP):

```
conf t
hostname CORE-SW-01
interface Vlan1
 ip address 192.168.1.201 255.255.255.0
 no shutdown
ip default-gateway 192.168.1.1
interface range GigabitEthernet0/0 - 3
 switchport mode access
 switchport access vlan 1
 no shutdown
end
write memory
```

**AP-01 (Alpine):** `ip addr add 192.168.1.221/24 dev eth0 && ip link set eth0 up`

**ตรวจว่าผ่าน** (จากเครื่อง Windows):

```powershell
Test-Connection 192.168.1.201,192.168.1.211,192.168.1.212,192.168.1.221 -Count 1 | Select Address,Status
# ทั้ง 4 ตัวต้องเป็น Success
docker run --rm --network netwatch-engine alpine ping -c 2 192.168.1.201
# ต้อง ping จากใน network ของ engine ได้ด้วย ไม่ใช่แค่จาก Windows
```

**ข้อผิดพลาดที่พบบ่อย**

- External Connector อยู่ในโหมด NAT: Windows ping ไม่ถึง
- Wi-Fi ของบางที่ (เช่น Wi-Fi มหาวิทยาลัย) กัน client คุยกันเอง (client isolation) ให้ใช้สาย LAN หรือ hotspot ของตัวเองแทน
- ชื่อ interface ของ IOSvL2 เป็น `GigabitEthernet0/x` ไม่ใช่ `1/0/x` แบบใน guide ทุกคำสั่งที่อ้าง `Gi1/0/1` ใน 2.5/2.6 ต้องเปลี่ยนตาม

---

## ขั้น A3 — SNMPv3 บนสวิตช์ใน CML (= guide 2.5 ส่วน config)

ใช้ config ตาม `docs/phase-2-guide.html` ขั้น 2.5 ได้เลย แค่เปลี่ยน 2 จุด:

```
ip access-list standard NETWATCH-SNMP
 permit host <IP ของเครื่อง Windows บน LAN>
 deny   any log
...
interface GigabitEthernet0/1
 load-interval 30
```

ต้องใช้ passphrase ชุดเดียวกับ `{$SNMPV3.AUTH}` / `{$SNMPV3.PRIV}` ที่ตั้งไว้ในขั้น 2.0

**ตรวจว่าผ่าน:**

```
show snmp user     ! Authentication Protocol: SHA / Privacy Protocol: AES128
show snmp group    ! security model:v3 priv  access-list: NETWATCH-SNMP
```

ทดสอบจาก network ของ engine ก่อนเพิ่ม host ลง Zabbix (ช่องที่ใส่ passphrase ให้พิมพ์เอง อย่าเก็บลงไฟล์):

```powershell
docker run --rm -it --network netwatch-engine alpine sh -c "apk add -q net-snmp-tools && snmpget -v3 -l authPriv -u netwatch-poll -a SHA -A '<AUTH>' -x AES -X '<PRIV>' 192.168.1.201 1.3.6.1.2.1.1.5.0"
# expect: SNMPv2-MIB::sysName.0 = STRING: CORE-SW-01
```

> **ต้องเช็กกับ image จริง:** IOSvL2 ใน CML บาง release อาจไม่มี `aes 128` ให้ใช้ ถ้า `snmp-server user` ไม่รับ `priv aes 128` ให้ดูด้วย `show version` ว่าเป็น image ที่มี crypto (K9) หรือเปล่า **ห้ามลดลงไปใช้ authNoPriv** เพราะผิด §9

---

## ขั้น A4 — Provision ตัวแรก (= guide 2.5 ส่วน provision)

`provisioning/inventory.csv` ลบ `# ` หน้าบรรทัด CORE ออกแล้วใส่ค่าจริง:

```
CORE-SW-01,Core Switch 01,core,acme-hq,HQ,192.168.1.201,Cisco IOSvL2 (CML),
```

ไม่ต้องแก้ `catalog.py` เพราะ template เลือกจาก `role` ส่วน `model` เป็นแค่ข้อความ

```powershell
nw provisioning.provision    # ~ host CORE-SW-01 created ... ADR 0004 check: PASS
nw provisioning.provision    # 0 changes
```

ใน UI ไปที่ CORE-SW-01 → Discovery rules แล้วกด **Execute now** ที่ "Network interfaces discovery" จากนั้นรอ 2–3 นาที

```powershell
nw provisioning.verify       # verify: PASS
nw provisioning.export       # created templates/netwatch/hosts/core-sw-01.yaml
```

**ข้อผิดพลาดที่พบบ่อย:** ใน ACL ต้องใส่ IP ของเครื่อง Windows ไม่ใช่ IP ของ container ให้ตรวจด้วย `show access-lists NETWATCH-SNMP` ซึ่ง counter ของบรรทัด permit ต้องเพิ่มขึ้น

---

## ขั้น A5 — เทียบ throughput (= guide 2.6)

traffic ใน CML นิ่งมาก จึงต้องสร้าง load เอง จาก ACC-SW-01:

```
ping 192.168.1.201 size 1500 repeat 1000000 timeout 0
```

แล้วเทียบผ่าน store ของเรา (ห้ามใช้ `history.get`):

```powershell
portal-login somchai
portal /api/devices/CORE-SW-01/latest | Where-Object metric -eq 'if_in_bps:Gi0/1'
```

ในเวลาเดียวกันบน CORE:

```
show interfaces GigabitEthernet0/1 | include rate
```

**ผ่านเมื่อ:** ค่าต่างกันไม่เกิน ±10% และต้องทดสอบให้ครบ 3 พอร์ต

**ข้อจำกัด:** data plane ของ IOSvL2 ช้า (ไม่กี่ Mbps) จึงทดสอบเรื่อง counter 64-bit ที่ 1G ไม่ได้ เพราะไม่มีทาง wrap ให้จดเป็นงานที่ต้องตรวจซ้ำบนอุปกรณ์จริง และรวมกับ open item "ค่า unsigned > 2^53" ใน `docs/phase-0-checklist.md`

---

## ขั้น A6 — Tag filter ของ Connector (= guide 2.7)

ทำตาม guide ได้ทั้งหมด ไม่มีอะไรที่ต่างเพราะ CML

---

## ขั้น A7 — Rollout + dependency (= guide 2.8)

เพิ่มลงใน `provisioning/inventory.csv`:

```
ACC-SW-01,Access Switch 01 (Floor 1),access,acme-hq,HQ,192.168.1.211,Cisco IOSvL2 (CML),CORE-SW-01
ACC-SW-02,Access Switch 02 (Floor 2),access,acme-hq,HQ,192.168.1.212,Cisco IOSvL2 (CML),CORE-SW-01
AP-01,AP Lobby,ap,acme-hq,HQ,192.168.1.221,Alpine (stand-in for Aruba),ACC-SW-01
```

```powershell
nw provisioning.provision    # ~ dependency ACC-SW-01 -> CORE-SW-01 ... PASS
nw provisioning.provision    # 0 changes
nw provisioning.verify       # verify: PASS
```

**ทดสอบ dependency:** ใน CML ทำได้จริงกว่าวิธีแก้ IP ใน guide เพราะดึง link ได้เลย ให้กด **Stop** ที่ node CORE-SW-01 แล้วรอประมาณ 6 นาที

```powershell
portal /api/problems | Select-Object device_ref, title
```

**ผ่านเมื่อ:** เห็น problem เดียวคือ `Cisco IOS: Unavailable by ICMP ping` ของ CORE-SW-01 ส่วน ACC/AP ไม่มี problem เลย จากนั้นกด Start ที่ CORE แล้ว problem ต้อง resolve

**ข้อผิดพลาดที่พบบ่อย:** ใน topology นี้ ACC/AP ต่อผ่าน CORE ทาง data plane จริง ถ้าไป Stop ตัว ACC ก่อน CORE ตัว ACC จะ fire ก่อน (dependency มีผลเฉพาะตอนที่ master เป็น PROBLEM อยู่แล้ว)

---

## ขั้น A8 — ปิด Phase 2

รันชุดตรวจใน guide ข้อ 12 ให้ครบ:

```powershell
nw provisioning.provision        # 0 changes, ทุก tenant PASS
nw provisioning.verify           # verify: PASS
nw provisioning.export           # unchanged ทุกไฟล์
cd backend; .venv\Scripts\python -m pytest -q; cd ..
boundary                         # check-boundary: OK
```

แล้วบันทึกผลลง `docs/phase-2-checklist.md` (รูปแบบเดียวกับ phase-0) โดยติดป้ายว่า **"ผ่านบน lab (CML)"** ส่วนที่ต้องตรวจซ้ำที่ site จริงมี: counter 64-bit ที่ 1G/10G, IOS/IOS-XE version จริง, NAT/ACL ของ site และ decision #3 (proxy)

---

## Track B — Phase 3: Frontend (เริ่มคู่ขนานได้หลัง A0)

**เงื่อนไขปิด phase:** ลูกค้า login แล้วเห็น overview, รายการอุปกรณ์, กราฟ และ problem แบบ live และ `boundary` ต้องได้ OK (เพราะ `frontend/` อยู่ใน guarded path)

### ต้องตัดสินใจก่อนเริ่ม

| # | Decision | แนะนำ |
|---|---|---|
| B-a | UI kit | **shadcn/ui + Tailwind** (MIT): โค้ด component อยู่ใน repo เราเอง จึงอธิบายได้ทุกบรรทัดตาม §5 |
| B-b | Units ของ metric (payload ไม่มี units) | ใส่ item tag `unit` คู่กับ `metric` แล้วให้ mapper อ่าน ทำแบบเดียวกับ ADR 0009 และเขียนเป็น ADR 0012 |
| B-c | Dev server | Vite dev server proxy `/api` ไปที่ backend เพื่อใช้ cookie เดียวกันและไม่ต้องตั้ง CORS |

### ขั้นตอน

| ขั้น | งาน | ไฟล์ | ตรวจว่าผ่าน |
|---|---|---|---|
| B1 | สร้างโปรเจกต์ด้วย `npm create vite@latest frontend -- --template react-ts` (เป็นเครื่องมือ scaffold ไม่ใช่การ clone) ตั้ง proxy | `frontend/vite.config.ts` | `npm run dev` แล้วเปิด `/api/devices` ผ่าน port ของ Vite ได้ |
| B2 | API client ตัวเดียว + type ที่ตรงกับ response (`device_ref`, `problem_ref`) | `frontend/src/api/client.ts`, `types.ts` | `npx tsc --noEmit` ผ่าน และ `boundary` ได้ OK |
| B3 | Login (cookie ตาม ADR 0008) | `frontend/src/pages/Login.tsx` | login ผิดต้องได้ 401 พร้อมข้อความ login ถูกต้องเข้า overview |
| B4 | Overview + Device list + Problems + SSE | `frontend/src/pages/*`, `src/hooks/useStream.ts` | push probe = 1 (Phase 0 ข้อ D) แล้ว problem ต้องโผล่ภายในไม่กี่วินาทีโดยไม่ต้อง refresh |
| B5 | กราฟ SVG เขียนเอง ส่ง `step` ตามความกว้างของกราฟ | `frontend/src/charts/LineChart.tsx` | ใน DevTools → Network จำนวนจุดที่ได้มาต้อง ≈ ความกว้าง px ไม่ใช่ข้อมูลดิบทั้งหมด |
| B6 | Build แล้วให้ backend serve | `main.py` serve `frontend/dist/` | `npm run build` แล้วเปิด `http://127.0.0.1:8000/` เห็น portal |

**ข้อผิดพลาดที่พบบ่อย**

- ตั้งชื่อ class/ตัวแปรว่า `zbx-*` หรือใช้ `hostid` ใน type: hook จะ block ทันที
- เรียก engine API ตรงจาก browser: ผิดทั้ง §3 และ §4
- ใช้ library กราฟที่ license ไม่ผ่าน ให้เขียน SVG เองตามแผน

---

## ลำดับงานที่ต้องพึ่งกัน

```
A0 Docker ──┬─▶ A1 decision CML ─▶ A2 topology ─▶ A3 SNMP ─▶ A4 core ─▶ A5 ─▶ A6 ─▶ A7 ─▶ A8 ปิด Phase 2
            └─▶ B1 ─▶ B2 ─▶ B3 ─▶ B4 ─▶ B5 ─▶ B6           (ใช้ probe ของ Phase 0 เป็นข้อมูลไปก่อนได้)
```

**ยังติดอยู่และไม่ขึ้นกับ CML:** decision #1 (Aruba: AOS-8 หรือ AOS-10) ต้องรอ PO ของลูกค้า และ decision #3 (proxy) ต้องปิดก่อน rollout ข้าม WAN

---

## ภาคผนวก — จาก lab (CML) ไปสู่ config แบบของจริง (ทำทีหลัง ไม่บล็อก Phase 2–3)

**หลักการ:** Phase 2 ปิดด้วยผล "ผ่านบน lab (CML)" ก่อน แล้วค่อยลดช่องว่างระหว่าง lab กับ site จริงตามลำดับด้านล่าง ผลจาก CML **ไม่ได้แทน** การตรวจกับอุปกรณ์จริง (§9)

### ช่องว่างที่รู้แล้ว

| เรื่อง | CML (IOSvL2) | อุปกรณ์จริงที่ site | ผลต่อเรา |
|---|---|---|---|
| ชื่อพอร์ต | `Gi0/x` | `Gi1/0/x` และ uplink 10G (`Te1/1/x`) | metric name `if_in_bps:<ifName>` เปลี่ยนตาม ต้องยืนยันด้วย ifName จริง |
| Sensor (fan/PSU/temp) | ไม่มี | มี | LLD ของ sensor ไม่ถูกทดสอบเลย |
| Counter 64-bit ที่ 1G/10G | data plane ช้า ไม่มีทาง wrap | ต้องไม่ติดลบ/ศูนย์เป็นระยะ | ต้องตรวจซ้ำบนของจริง |
| IOS version / SNMPv3 algorithm | image ของ CML | ขึ้นกับรุ่น (บางรุ่นไม่มี SHA-2/AES256) | ต้องให้ `catalog.py` ตรงกับ switch |
| ค่า 3 ตัว/ระยะเวลาของ ICMP | LAN เดียวกัน | ข้าม WAN/NAT/ACL ของ site | ผูกกับ decision #3 (proxy) |

### ขั้นที่เพิ่มทีหลัง (เรียงตามความคุ้ม)

1. **ทำให้ config lab เหมือนของจริงที่สุดเท่าที่ทำได้ (ทำใน CML เลย)**
   - ตั้งชื่อ/เลข interface ให้ใกล้ของ site (เช่น ใช้ node ที่มีพอร์ตมากพอ) และเปิด `snmp-server ifindex persist`, `load-interval 30`
   - ใช้ ACL, VLAN และ SVI แบบเดียวกับ design ของ site
   - ใช้ SNMPv3 algorithm ชุดเดียวกับที่ site รองรับ (ถามรุ่นก่อน แล้วค่อยเลือก SHA/AES128 หรือ SHA-2/AES256 ใน `catalog.py`)
2. **ขอ config จริงจากลูกค้า/ทีมติดตั้ง** (sanitize รหัสผ่านแล้ว): `show running-config`, `show version`, `show inventory` ใช้เทียบกับ lab และดูว่ารุ่นไหนมี sensor/SNMP feature อะไร
3. **ลอง image อื่น/CML node อื่น** ถ้าลิขสิทธิ์มี (เช่น IOL, Cat8000v/CSR1000v สำหรับ IOS-XE) เพื่อดูพฤติกรรม ifName และ SNMP ของ IOS-XE
4. **ตรวจกับอุปกรณ์จริงที่ site 1 ตัวก่อน** ตามหลัก "one device first" (§9) แล้วทำซ้ำ 2.5–2.7: `show interfaces` เทียบ throughput 3 พอร์ต, ตรวจ sensor LLD, ตรวจ counter 64-bit ที่ uplink
5. **ปิดช่องว่าง Aruba** เมื่อ decision #1 ปิด (AOS-8 หรือ AOS-10) ตอนนี้ AP-01 ใน lab เป็นแค่ ICMP

### ตรวจว่าผ่าน (เมื่อขึ้น site จริง)

```powershell
nw provisioning.verify                       # verify: PASS, ไม่มี unsupported item
(portal /api/devices/<DEVICE>/latest).metric | Where-Object { $_ -like 'if_in_bps:*' }
# ต้องเห็นชื่อพอร์ตตรงกับ ifName จริงบน switch (ตรวจด้วย snmpwalk 1.3.6.1.2.1.31.1.1.1.1)
```

บันทึกผลลง `docs/phase-2-checklist.md` แยกเป็น 2 ป้าย: **"ผ่านบน lab (CML)"** และ **"ผ่านที่ site จริง"**

### ข้อผิดพลาดที่พบบ่อย

- เห็นว่าผ่านบน CML แล้วถือว่าเสร็จ: sensor, counter 64-bit และชื่อพอร์ตยังไม่ได้ถูกทดสอบเลย
- ฮาร์ดโค้ดชื่อพอร์ตแบบ `Gi0/1` ไว้ในโค้ดหรือ test: ชื่อต้องมาจากข้อมูลที่ engine ส่งมาเท่านั้น
- ลด SNMPv3 เป็น authNoPriv เพื่อให้ image ใช้ได้: ผิด §9 ให้เปลี่ยน image แทน
