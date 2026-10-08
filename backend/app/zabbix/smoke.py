"""Check the API client against the running engine.

    cd backend
    .venv\\Scripts\\python -m app.zabbix.smoke
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.zabbix.client import ZabbixAPIError, ZabbixClient


async def main() -> None:
    settings = get_settings()
    if not settings.engine_token:
        raise SystemExit("ENGINE_TOKEN is not set in backend/.env")
    async with ZabbixClient(settings.engine_url) as client:
        print("version:", await client.version())

        hosts = await client.call(
            "host.get", {"output": ["host"]}, token=settings.engine_token
        )
        print("hosts:", [h["host"] for h in hosts])

        try:
            await client.call("host.get", {"output": ["host"]}, token="0" * 64)
            print("bad token: ACCEPTED  <-- this is a failure")
        except ZabbixAPIError as exc:
            print("bad token rejected:", exc)


if __name__ == "__main__":
    asyncio.run(main())
