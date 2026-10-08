"""Add portal tenants and users by hand (until provisioning does it, Phase 2).

    cd backend
    .venv\\Scripts\\python -m app.auth.cli add-tenant acme-hq "ACME HQ"
        (asks for the tenant's read token, input hidden)
    .venv\\Scripts\\python -m app.auth.cli add-user alice acme-hq
        (asks for the password, input hidden)

Secrets are read with getpass, never from the command line, so they do not
end up in shell history.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass

from app.config import get_settings
from app.container import build_container
from app.domain.models import Tenant


async def _run(args: argparse.Namespace) -> None:
    container = build_container(get_settings())
    await container.start()
    try:
        if args.command == "add-tenant":
            token = getpass.getpass(f"read token for tenant {args.tenant_id}: ").strip()
            if not token:
                raise SystemExit("empty token")
            await container.auth.add_tenant(Tenant(args.tenant_id, args.name, token))
            print(f"tenant {args.tenant_id} saved (token encrypted at rest)")
        else:
            password = getpass.getpass(f"password for {args.username}: ")
            if len(password) < 12:
                raise SystemExit("password must be at least 12 characters")
            if password != getpass.getpass("again: "):
                raise SystemExit("passwords differ")
            await container.auth.add_user(args.username, args.tenant_id, password)
            print(f"user {args.username} saved in tenant {args.tenant_id}")
    finally:
        await container.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.auth.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("add-tenant")
    t.add_argument("tenant_id")
    t.add_argument("name")
    u = sub.add_parser("add-user")
    u.add_argument("username")
    u.add_argument("tenant_id")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
