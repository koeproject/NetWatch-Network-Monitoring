"""What each inventory role becomes in the engine.

Shared vocabulary with backend/app/zabbix/mapper.py:
- host tag "role" values must be keys of mapper._KIND (core, access, ap, server)
- host tag "site" becomes Device.site
- item tag "metric" is our metric name (mapper.metric_name)
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# NETWATCH_INVENTORY points at another CSV, e.g. the lab stand-in
# (provisioning/lab-standin.csv) so lab hosts never enter the real inventory.
INVENTORY = Path(os.environ.get("NETWATCH_INVENTORY") or Path(__file__).with_name("inventory.csv"))

TEMPLATE_PREFIX = "NetWatch "
METRIC_TAG = "metric"
REACHABILITY_TAG = ("netwatch", "reachability")
SNMP_MACROS = ("{$SNMPV3.USER}", "{$SNMPV3.AUTH}", "{$SNMPV3.PRIV}")

# Engine numbering. Interface type: 1 agent, 2 SNMP.
IF_AGENT = 1
IF_SNMP = 2
# SNMP interface details on 7.0: securitylevel 2 = authPriv, authprotocol
# 1 = SHA1, privprotocol 1 = AES128. Must match the switch (step 2.5).
SNMP_DETAILS: dict[str, Any] = {
    "version": 3,
    "bulk": 1,
    "securityname": SNMP_MACROS[0],
    "securitylevel": 2,
    "authprotocol": 1,
    "authpassphrase": SNMP_MACROS[1],
    "privprotocol": 1,
    "privpassphrase": SNMP_MACROS[2],
}
# hostgroup_rights permission: 2 = read-only.
READ = 2


@dataclass(frozen=True)
class Role:
    templates: tuple[str, ...]
    interface_type: int


ROLES: dict[str, Role] = {
    "core": Role(("NetWatch Cisco IOS by SNMP",), IF_SNMP),
    "access": Role(("NetWatch Cisco IOS by SNMP",), IF_SNMP),
    # Aruba waits on decision #1 (AOS-8 vs AOS-10). Reachability only until then.
    "ap": Role(("NetWatch ICMP Ping",), IF_AGENT),
}

TENANTS: dict[str, str] = {
    "acme-hq": "ACME HQ",
    "branch-co": "Branch Co",
}


@dataclass(frozen=True)
class Device:
    technical_name: str
    display_name: str
    role: str
    tenant: str
    site: str
    address: str
    model: str
    parent: str

    @property
    def group(self) -> str:
        # The host group IS the tenancy boundary (ADR 0004): never shared by two tenants.
        return f"tenant/{self.tenant}/{self.site}"

    def interface(self) -> dict[str, Any]:
        kind = ROLES[self.role].interface_type
        iface: dict[str, Any] = {"type": kind, "main": 1, "useip": 1, "ip": self.address, "dns": ""}
        if kind == IF_SNMP:
            return {**iface, "port": "161", "details": dict(SNMP_DETAILS)}
        # ICMP needs an IP to ping; the agent interface is only its carrier.
        return {**iface, "port": "10050"}


def load_inventory(path: Path = INVENTORY) -> list[Device]:
    with path.open(newline="", encoding="utf-8") as f:
        # Skip blank lines too: a blank line before the header would become the header.
        rows = list(csv.DictReader(line for line in f if line.strip() and not line.startswith("#")))
    devices = [Device(**{k: (v or "").strip() for k, v in row.items()}) for row in rows]

    names = [d.technical_name for d in devices]
    errors = [f"duplicate technical_name {n}" for n in sorted({n for n in names if names.count(n) > 1})]
    for d in devices:
        if d.role not in ROLES:
            errors.append(f"{d.technical_name}: unknown role {d.role!r}")
        if d.tenant not in TENANTS:
            errors.append(f"{d.technical_name}: unknown tenant {d.tenant!r} (add it to TENANTS)")
        if d.parent and d.parent not in names:
            errors.append(f"{d.technical_name}: parent {d.parent!r} is not in the inventory")
        if not d.address or not d.site:
            errors.append(f"{d.technical_name}: address and site are required")
    if errors:
        raise SystemExit("inventory.csv:\n  " + "\n  ".join(errors))
    return devices