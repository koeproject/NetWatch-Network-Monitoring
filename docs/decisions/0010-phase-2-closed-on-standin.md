# 0010 — Phase 2 closes on a net-snmp stand-in; Cisco checks move to lab/site

- Status: **Accepted**
- Date: 2026-10-15
- Affects: `lab/snmp-standin/`, `provisioning/lab-standin.csv`,
  `provisioning/catalog.py` (`NETWATCH_INVENTORY`), `docs/phase-2-checklist.md`

## Context

Phase 2 steps 2.5, 2.6 and the rollout half of 2.8 need a switch to poll.
There is no Cisco hardware and no CML lab yet (where CML runs is still open).
Phase 3 should not wait for that.

## Decision

Close Phase 2 **conditionally**, on three Linux net-snmp containers
(`lab/snmp-standin/`) that stand in for core, access and AP:

- SNMPv3 authPriv (SHA + AES128) only, same as `catalog.SNMP_DETAILS`;
  authNoPriv and wrong passphrases are refused, as on a switch.
- Polled with our real clone `NetWatch Cisco IOS by SNMP`, provisioned by the
  real `provision.py` from a separate inventory (`provisioning/lab-standin.csv`,
  selected with `NETWATCH_INVENTORY`) so lab hosts never enter `inventory.csv`.
- Lab passphrases are random, live in gitignored `lab/snmp-standin/.env`, and are
  set as **host** secret macros on the stand-ins only. Global `{$SNMPV3.*}` are
  untouched.

## What this proves, and what it does not

Proven on the stand-in (2026-10-15, Zabbix 7.0.29): SNMPv3 authPriv through the
engine, interface LLD, `metric` tag names (`if_in_bps:eth0`), 64-bit counters and
the bits multiplier (store 20.04 Mbit/s vs iperf3 20 Mbit/s vs kernel 20.04),
Connector tag filter, the 3-level dependency chain with real outages, and
provisioning idempotence.

**Not** proven — must be repeated on CML or real Cisco before go-live (§9):
Cisco MIB items (CPU, memory, sensors, model/serial/OS: unsupported on net-snmp),
Cisco ifName format (`Gi1/0/1`), IOS SNMPv3 algorithm support, counters at
1G/10G, and the site's NAT/ACL path. `verify.py` therefore reports FAIL on the
stand-in for exactly three Cisco-only items per host; that is the expected result.

## Consequences

- Phase 3 can start; the stand-ins also give it live data.
- `docs/phase-2-checklist.md` labels 2.5/2.6/2.8 "ผ่านบน stand-in" with an open
  "ผ่านบน Cisco" column.
- The CML decision is renumbered to ADR 0011 when written.
