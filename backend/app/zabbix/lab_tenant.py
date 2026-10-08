"""Phase 1 lab: one read-only tenant, so the read path can be tested end to end.

Until provisioning/provision.py exists (Phase 2), this creates in the engine:
  user group  acme-lab-readers   read on host group "Zabbix servers"
  user        acme-lab-reader    role "User role" (roleid 1), random password
  API token   acme-read          for that user
and saves tenant "lab" in OUR store with that token (encrypted at rest).
Then it runs ADR 0004's check: with the tenant token, host.get must return
exactly the hosts of that group.

Idempotent: re-running regenerates the token and re-saves the tenant.

Runs inside the backend container (it needs our store and the engine API):
    docker compose -f backend/docker-compose.dev.yml exec -T \\
        -e ENGINE_TOKEN="$ENGINE_TOKEN" backend python -m app.zabbix.lab_tenant
"""

from __future__ import annotations

import asyncio
import secrets

from app.config import get_settings
from app.container import build_container
from app.domain.models import Tenant
from app.zabbix.client import ZabbixClient

HOST_GROUP = "Zabbix servers"
USER_GROUP = "acme-lab-readers"
USERNAME = "acme-lab-reader"
TOKEN_NAME = "acme-read"
USER_ROLE_ID = "1"  # built-in "User role" on 7.0 — check with role.get if unsure
READ = 2  # hostgroup_rights permission: 2 = read-only, 3 = read-write
TENANT_ID = "lab"


async def _one_id(client: ZabbixClient, method: str, key: str, filt: dict, admin: str) -> str | None:
    found = await client.call(method, {"output": [key], "filter": filt}, token=admin)
    return found[0][key] if found else None


async def main() -> None:
    settings = get_settings()
    admin = settings.engine_token
    if not admin:
        raise SystemExit("pass the admin token: exec -e ENGINE_TOKEN=... (it is not in the container)")

    async with ZabbixClient(settings.engine_url) as client:
        groupid = await _one_id(client, "hostgroup.get", "groupid", {"name": [HOST_GROUP]}, admin)
        if groupid is None:
            raise SystemExit(f"host group {HOST_GROUP!r} not found")

        rights = [{"id": groupid, "permission": READ}]
        usrgrpid = await _one_id(client, "usergroup.get", "usrgrpid", {"name": [USER_GROUP]}, admin)
        if usrgrpid is None:
            created = await client.call(
                "usergroup.create", {"name": USER_GROUP, "hostgroup_rights": rights}, token=admin
            )
            usrgrpid = created["usrgrpids"][0]
        else:
            await client.call(
                "usergroup.update", {"usrgrpid": usrgrpid, "hostgroup_rights": rights}, token=admin
            )

        userid = await _one_id(client, "user.get", "userid", {"username": [USERNAME]}, admin)
        if userid is None:
            created = await client.call(
                "user.create",
                {
                    "username": USERNAME,
                    # Nobody logs in with it: the API token is the only way in.
                    "passwd": secrets.token_urlsafe(24),
                    "roleid": USER_ROLE_ID,
                    "usrgrps": [{"usrgrpid": usrgrpid}],
                },
                token=admin,
            )
            userid = created["userids"][0]

        old = await client.call(
            "token.get", {"output": ["tokenid"], "userids": [userid], "filter": {"name": [TOKEN_NAME]}},
            token=admin,
        )
        if old:
            await client.call("token.delete", [t["tokenid"] for t in old], token=admin)
        tokenid = (await client.call(
            "token.create", {"name": TOKEN_NAME, "userid": userid}, token=admin
        ))["tokenids"][0]
        tenant_token = (await client.call("token.generate", [tokenid], token=admin))[0]["token"]

        # ADR 0004 check: the tenant token sees exactly the group's hosts.
        expected = {
            h["host"] for h in await client.call(
                "host.get", {"output": ["host"], "groupids": [groupid]}, token=admin
            )
        }
        seen = {h["host"] for h in await client.call("host.get", {"output": ["host"]}, token=tenant_token)}
        print(f"ADR 0004 check, tenant {TENANT_ID}: {'PASS' if seen == expected else 'FAIL'} "
              f"(sees {sorted(seen)}, expected {sorted(expected)})")

    container = build_container(settings)
    await container.start()
    try:
        await container.auth.add_tenant(Tenant(TENANT_ID, "Lab tenant", tenant_token))
    finally:
        await container.stop()
    print(f"tenant {TENANT_ID!r} saved in our store (token encrypted; not printed)")


if __name__ == "__main__":
    asyncio.run(main())
