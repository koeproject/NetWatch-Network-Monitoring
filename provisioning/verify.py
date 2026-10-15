"""Check the engine against provisioning/inventory.csv. Read-only.

    nw provisioning.verify

Per device: in the engine, SNMP interface available, no unsupported items,
items tagged "metric" exist, exactly one reachability trigger.
Also: global SNMPv3 macros exist, no stray hosts in tenant groups. Exit 1 on FAIL.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings
from app.zabbix.client import ZabbixClient
from provisioning.catalog import IF_SNMP, METRIC_TAG, REACHABILITY_TAG, SNMP_MACROS, load_inventory

# hostinterface available: 1 = available. item state: 1 = not supported.
AVAILABLE = "1"
NOT_SUPPORTED = 1


async def main() -> int:
    settings = get_settings()
    admin = settings.engine_token
    if not admin:
        raise SystemExit("pass the admin token: -e ENGINE_TOKEN=...")
    devices = load_inventory()
    failed = 0

    async with ZabbixClient(settings.engine_url) as client:
        async def call(method: str, params: Any) -> Any:
            return await client.call(method, params, token=admin)

        macros = {m["macro"] for m in await call("usermacro.get", {"output": ["macro"], "globalmacro": True})}
        missing = sorted(set(SNMP_MACROS) - macros)
        print(f"{'global macros':<16} {'PASS' if not missing else 'FAIL missing ' + ', '.join(missing)}")
        failed += bool(missing)

        tag, value = REACHABILITY_TAG
        # An empty name filter is no filter: skip the lookup when there is nothing to check.
        found = await call("host.get", {
            "output": ["hostid", "host"],
            "filter": {"host": [d.technical_name for d in devices]},
            "selectInterfaces": ["type", "available", "error"],
        }) if devices else []
        hosts = {h["host"]: h for h in found}

        for d in devices:
            h = hosts.get(d.technical_name)
            if h is None:
                print(f"{d.technical_name:<16} FAIL  not in the engine (run provisioning.provision)")
                failed += 1
                continue
            problems: list[str] = []

            for i in h["interfaces"]:
                if str(i["type"]) == str(IF_SNMP) and str(i["available"]) != AVAILABLE:
                    problems.append(f"SNMP interface not available: {i.get('error') or 'not polled yet'}")

            unsupported = await call("item.get", {
                "hostids": [h["hostid"]], "output": ["name", "error"],
                "filter": {"state": NOT_SUPPORTED},
            })
            for item in unsupported[:5]:
                problems.append(f"unsupported: {item['name']}: {item['error']}")
            if len(unsupported) > 5:
                problems.append(f"... and {len(unsupported) - 5} more unsupported")

            tagged = int(await call("item.get", {
                "hostids": [h["hostid"]], "countOutput": True,
                "tags": [{"tag": METRIC_TAG, "operator": 4}],  # 4 = exists
            }))
            if tagged == 0:
                problems.append(f"no items tagged {METRIC_TAG}: nothing will reach our store")
            reach = int(await call("trigger.get", {
                "hostids": [h["hostid"]], "countOutput": True,
                "tags": [{"tag": tag, "value": value, "operator": 1}],
            }))
            if reach != 1:
                problems.append(f"{reach} triggers tagged {tag}={value}, expected 1")
            print(f"{d.technical_name:<16} {'PASS' if not problems else 'FAIL'}  ({tagged} metric items)")
            for p in problems:
                print(f"    - {p}")
            failed += bool(problems)

        groups = await call("hostgroup.get", {"output": ["groupid"], "search": {"name": "tenant/"}, "startSearch": True})
        if groups:
            in_groups = {h["host"] for h in await call("host.get", {
                "output": ["host"], "groupids": [g["groupid"] for g in groups],
            })}
            stray = sorted(in_groups - {d.technical_name for d in devices})
            print(f"{'stray hosts':<16} {'PASS' if not stray else 'FAIL ' + ', '.join(stray)}")
            failed += bool(stray)

    print("verify: " + ("PASS" if not failed else f"FAIL ({failed})"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
