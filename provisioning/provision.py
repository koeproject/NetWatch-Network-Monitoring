"""Push provisioning/inventory.csv into the engine and our store. Idempotent.

    nw provisioning.provision

  1. templates    import templates/netwatch/templates/*.yaml where they differ
  2. host groups  tenant/<tenant>/<site>
  3. hosts        create or update name, group, tags, templates, interface
  4. dependencies a device's reachability trigger depends on its parent's
  5. tenants      user group (read on its groups) + user + API token
  6. ADR 0004     each tenant token sees exactly its inventory hosts -> PASS/FAIL

A second run with no inventory change must print "0 changes".
"""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.container import Container, build_container
from app.domain.models import Tenant
from app.zabbix.client import ZabbixAPIError, ZabbixClient
from provisioning.catalog import READ, REACHABILITY_TAG, ROLES, TENANTS, Device, load_inventory

ROOT = Path(__file__).resolve().parent.parent
OUR_TEMPLATES = ROOT / "templates" / "netwatch" / "templates"
USER_ROLE_ID = "1"  # built-in "User role" on 7.0 — check with role.get if unsure
TOKEN_NAME = "netwatch-read"

_UPSERT = {"createMissing": True, "updateExisting": True}
# The YAML in git is the source of truth: what is not in it is removed from our templates.
_SYNC = {**_UPSERT, "deleteMissing": True}
IMPORT_RULES = {
    "template_groups": _UPSERT,
    "templates": _UPSERT,
    "items": _SYNC,
    "triggers": _SYNC,
    "discoveryRules": _SYNC,
    "graphs": _SYNC,
    "valueMaps": _SYNC,
    "templateDashboards": _SYNC,
    "templateLinkage": {"createMissing": True},
}


class Run:
    def __init__(self, client: ZabbixClient, admin: str) -> None:
        self.client = client
        self.admin = admin
        self.changes = 0
        self.errors = 0

    async def call(self, method: str, params: Any) -> Any:
        return await self.client.call(method, params, token=self.admin)

    def changed(self, what: str) -> None:
        self.changes += 1
        print(f"  ~ {what}")

    def failed(self, what: str) -> None:
        # Keep going so one bad device does not hide the rest, but exit 1 at the end.
        self.errors += 1
        print(f"  ! {what}")


# -- 1. templates ---------------------------------------------------------------
async def import_templates(run: Run) -> None:
    for path in sorted(OUR_TEMPLATES.glob("*.yaml")):
        params = {"format": "yaml", "source": path.read_text(encoding="utf-8"), "rules": IMPORT_RULES}
        if not await run.call("configuration.importcompare", params):
            continue
        await run.call("configuration.import", params)
        run.changed(f"template imported from {path.name}")


# -- 2. host groups -------------------------------------------------------------
async def ensure_groups(run: Run, names: set[str]) -> dict[str, str]:
    found = await run.call("hostgroup.get", {"output": ["groupid", "name"], "filter": {"name": sorted(names)}})
    ids = {g["name"]: g["groupid"] for g in found}
    for name in sorted(names - ids.keys()):
        ids[name] = (await run.call("hostgroup.create", {"name": name}))["groupids"][0]
        run.changed(f"host group {name}")
    return ids


# -- 3. hosts -------------------------------------------------------------------
async def template_ids(run: Run, names: set[str]) -> dict[str, str]:
    found = await run.call("template.get", {"output": ["templateid", "host"], "filter": {"host": sorted(names)}})
    ids = {t["host"]: t["templateid"] for t in found}
    if missing := names - ids.keys():
        raise SystemExit(f"templates not in the engine: {sorted(missing)} (step 2.2)")
    return ids


def _same_interface(have: dict[str, Any], want: dict[str, Any]) -> bool:
    if any(str(have[k]) != str(want[k]) for k in ("type", "ip", "port")):
        return False
    have_details = have.get("details") or {}
    if isinstance(have_details, list):  # agent interfaces come back as []
        have_details = {}
    return all(str(have_details.get(k)) == str(v) for k, v in want.get("details", {}).items())


async def ensure_hosts(
    run: Run, devices: list[Device], groups: dict[str, str], templates: dict[str, str]
) -> dict[str, str]:
    found = await run.call("host.get", {
        "output": ["hostid", "host", "name"],
        "filter": {"host": [d.technical_name for d in devices]},
        "selectHostGroups": ["groupid"],
        "selectParentTemplates": ["templateid"],
        "selectTags": ["tag", "value"],
        "selectInterfaces": ["interfaceid", "type", "main", "ip", "port", "details"],
    })
    existing = {h["host"]: h for h in found}
    ids: dict[str, str] = {}

    for d in devices:
        want = {
            "name": d.display_name,
            "groups": [{"groupid": groups[d.group]}],
            "tags": [
                {"tag": "role", "value": d.role},
                {"tag": "site", "value": d.site},
                {"tag": "model", "value": d.model},
            ],
            "templates": [{"templateid": templates[t]} for t in ROLES[d.role].templates],
        }
        iface = d.interface()
        have = existing.get(d.technical_name)

        if have is None:
            created = await run.call("host.create", {"host": d.technical_name, **want, "interfaces": [iface]})
            ids[d.technical_name] = created["hostids"][0]
            run.changed(f"host {d.technical_name} created")
            continue

        hostid = ids[d.technical_name] = have["hostid"]
        if (
            have["name"] != want["name"]
            or {g["groupid"] for g in have["hostgroups"]} != {g["groupid"] for g in want["groups"]}
            or {(t["tag"], t["value"]) for t in have["tags"]} != {(t["tag"], t["value"]) for t in want["tags"]}
            or {t["templateid"] for t in have["parentTemplates"]} != {t["templateid"] for t in want["templates"]}
        ):
            await run.call("host.update", {"hostid": hostid, **want})
            run.changed(f"host {d.technical_name} updated")

        main = next(
            (i for i in have["interfaces"] if str(i["main"]) == "1" and str(i["type"]) == str(iface["type"])),
            None,
        )
        if main is None:
            raise SystemExit(f"{d.technical_name}: no main interface of type {iface['type']} (role changed? fix by hand)")
        if not _same_interface(main, iface):
            update = {k: iface[k] for k in ("ip", "port", "details") if k in iface}
            await run.call("hostinterface.update", {"interfaceid": main["interfaceid"], **update})
            run.changed(f"host {d.technical_name} interface updated")

    return ids


# -- 4. dependencies ------------------------------------------------------------
async def reachability_trigger(run: Run, hostid: str, host: str) -> dict[str, Any] | None:
    tag, value = REACHABILITY_TAG
    found = await run.call("trigger.get", {
        "hostids": [hostid],
        "output": ["triggerid", "description"],
        "tags": [{"tag": tag, "value": value, "operator": 1}],  # 1 = equals
        "selectDependencies": ["triggerid"],
    })
    if len(found) != 1:
        run.failed(f"{host}: expected 1 trigger tagged {tag}={value}, found {len(found)} (step 2.2)")
        return None
    return found[0]


async def ensure_dependencies(run: Run, devices: list[Device], host_ids: dict[str, str]) -> None:
    for d in devices:
        if not d.parent:
            continue
        child = await reachability_trigger(run, host_ids[d.technical_name], d.technical_name)
        parent = await reachability_trigger(run, host_ids[d.parent], d.parent)
        if child is None or parent is None:
            continue
        have = [t["triggerid"] for t in child["dependencies"]]
        if parent["triggerid"] in have:
            continue
        # 7.0 has no trigger.adddependencies (-32601). trigger.update replaces the
        # whole list, so keep what is there; it works on template-inherited triggers.
        deps = [{"triggerid": t} for t in [*have, parent["triggerid"]]]
        try:
            await run.call("trigger.update", {"triggerid": child["triggerid"], "dependencies": deps})
        except ZabbixAPIError as exc:
            run.failed(f"dependency {d.technical_name} -> {d.parent}: {exc}")
            continue
        run.changed(f"dependency {d.technical_name} -> {d.parent}")


# -- 5. tenants -----------------------------------------------------------------
async def _token_works(client: ZabbixClient, token: str) -> bool:
    try:
        await client.call("host.get", {"output": ["hostid"], "limit": 1}, token=token)
    except ZabbixAPIError:
        return False
    return True


async def ensure_tenant(run: Run, container: Container, tenant_id: str, groupids: list[str]) -> str:
    rights = [{"id": g, "permission": READ} for g in groupids]
    group_name = f"netwatch-{tenant_id}-readers"
    username = f"netwatch-{tenant_id}-reader"

    found = await run.call("usergroup.get", {
        "output": ["usrgrpid"], "filter": {"name": [group_name]},
        "selectHostGroupRights": ["id", "permission"],
    })
    if not found:
        usrgrpid = (await run.call("usergroup.create", {"name": group_name, "hostgroup_rights": rights}))["usrgrpids"][0]
        run.changed(f"user group {group_name}")
    else:
        usrgrpid = found[0]["usrgrpid"]
        have = {(r["id"], str(r["permission"])) for r in found[0]["hostgroup_rights"]}
        if have != {(r["id"], str(r["permission"])) for r in rights}:
            await run.call("usergroup.update", {"usrgrpid": usrgrpid, "hostgroup_rights": rights})
            run.changed(f"user group {group_name} rights")

    found = await run.call("user.get", {"output": ["userid"], "filter": {"username": [username]}})
    if found:
        userid = found[0]["userid"]
    else:
        userid = (await run.call("user.create", {
            "username": username,
            # Nobody logs in with it: the API token is the only way in.
            "passwd": secrets.token_urlsafe(24),
            "roleid": USER_ROLE_ID,
            "usrgrps": [{"usrgrpid": usrgrpid}],
        }))["userids"][0]
        run.changed(f"user {username}")

    stored = await container.store.get_tenant(tenant_id)
    if stored is not None and await _token_works(run.client, stored.engine_token):
        token = stored.engine_token
    else:
        old = await run.call("token.get", {
            "output": ["tokenid"], "userids": [userid], "filter": {"name": [TOKEN_NAME]},
        })
        if old:
            await run.call("token.delete", [t["tokenid"] for t in old])
        tokenid = (await run.call("token.create", {"name": TOKEN_NAME, "userid": userid}))["tokenids"][0]
        token = (await run.call("token.generate", [tokenid]))[0]["token"]
        run.changed(f"tenant {tenant_id}: new read token")

    if stored is None or stored.engine_token != token or stored.name != TENANTS[tenant_id]:
        await container.auth.add_tenant(Tenant(tenant_id, TENANTS[tenant_id], token))
        print(f"  tenant {tenant_id!r} saved in our store (token encrypted; not printed)")
    return token


# -- 6. ADR 0004 ----------------------------------------------------------------
async def adr_0004_check(run: Run, tenant_id: str, token: str, devices: list[Device]) -> bool:
    expected = {d.technical_name for d in devices if d.tenant == tenant_id}
    seen = {h["host"] for h in await run.client.call("host.get", {"output": ["host"]}, token=token)}
    ok = seen == expected
    detail = "" if ok else f" (sees {sorted(seen)}, expected {sorted(expected)})"
    print(f"ADR 0004 check, tenant {tenant_id}: {'PASS' if ok else 'FAIL'}{detail}")
    return ok


async def main() -> int:
    settings = get_settings()
    admin = settings.engine_token
    if not admin:
        raise SystemExit("pass the admin token: -e ENGINE_TOKEN=...")
    devices = load_inventory()
    if not devices:
        # Every lookup below filters on names; an empty filter is no filter.
        raise SystemExit("inventory.csv lists no devices yet (step 2.5)")

    container = build_container(settings)
    await container.start()
    try:
        async with ZabbixClient(settings.engine_url) as client:
            run = Run(client, admin)
            print("templates")
            await import_templates(run)
            print("host groups")
            groups = await ensure_groups(run, {d.group for d in devices})
            print("hosts")
            templates = await template_ids(run, {t for d in devices for t in ROLES[d.role].templates})
            host_ids = await ensure_hosts(run, devices, groups, templates)
            print("dependencies")
            await ensure_dependencies(run, devices, host_ids)
            print("tenants")
            all_ok = True
            for tenant_id in sorted({d.tenant for d in devices}):
                groupids = sorted({groups[d.group] for d in devices if d.tenant == tenant_id})
                token = await ensure_tenant(run, container, tenant_id, groupids)
                all_ok &= await adr_0004_check(run, tenant_id, token, devices)
    finally:
        await container.stop()

    print(f"{run.changes} changes" + (f", {run.errors} errors (lines with !)" if run.errors else ""))
    return 0 if all_ok and not run.errors else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
