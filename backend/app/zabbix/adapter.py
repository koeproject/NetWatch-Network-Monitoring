"""MonitoringEnginePort, implemented over the JSON-RPC client.

Lookups only. The token comes from the caller on every call (ADR 0004) —
this class holds no token of its own.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.domain.models import Device
from app.domain.ports import DeviceNotFound, EngineUnavailable
from app.zabbix import mapper
from app.zabbix.client import ZabbixAPIError, ZabbixClient

_HOST_QUERY: dict[str, Any] = {
    # No lastvalue anywhere: ADR 0005.
    "output": ["host", "name", "status", "maintenance_status"],
    "selectInterfaces": ["available"],
    "selectTags": ["tag", "value"],
    "sortfield": "name",
}


class ZabbixAdapter:
    def __init__(self, client: ZabbixClient) -> None:
        self._client = client

    async def _hosts(self, params: dict[str, Any], token: str) -> list[dict[str, Any]]:
        try:
            return await self._client.call("host.get", params, token=token)
        except (ZabbixAPIError, httpx.HTTPError) as exc:
            # The message stays in our logs; the API layer only sees the port's error.
            raise EngineUnavailable(str(exc)) from exc

    async def list_devices(self, token: str) -> list[Device]:
        return [mapper.device_from_api(h) for h in await self._hosts(_HOST_QUERY, token)]

    async def get_device(self, ref: str, token: str) -> Device:
        params = {**_HOST_QUERY, "filter": {"host": [mapper.host_from_device_ref(ref)]}}
        hosts = await self._hosts(params, token)
        if not hosts:
            raise DeviceNotFound(ref)
        return mapper.device_from_api(hosts[0])
