"""JSON-RPC 2.0 client for the engine's HTTP API.

Configuration path only (CLAUDE.md §3): host/template/item/trigger CRUD,
provisioning, on-demand lookups. Never graphs, never history — those come
from our own store, fed by the Connector.

The token is a required argument on every call and is never read from
config.py (decision #4): the same client serves the admin token for
provisioning and a per-tenant token for the read path, and the caller must
say which one it means.
"""

from __future__ import annotations

import itertools
from typing import Any

import httpx

API_PATH = "/api_jsonrpc.php"


class ZabbixAPIError(Exception):
    """The engine answered, and the answer was a JSON-RPC error object."""

    def __init__(self, method: str, code: int, message: str, data: str = "") -> None:
        super().__init__(f"{method}: [{code}] {message} {data}".rstrip())
        self.method = method
        self.code = code
        self.message = message
        self.data = data


class ZabbixClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + API_PATH
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._ids = itertools.count(1)

    async def __aenter__(self) -> ZabbixClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(
        self,
        method: str,
        params: dict[str, Any] | list[Any] | None = None,
        *,
        token: str | None,
    ) -> Any:
        """Call one API method and return its "result" member.

        ``token`` has no default on purpose: None means "this method takes no
        auth" (apiinfo.version, user.login), and must be said out loud.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params if params is not None else {},
            "id": next(self._ids),
        }
        headers = {"Content-Type": "application/json-rpc"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"

        response = await self._http.post(self._url, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()

        if "error" in body:
            error = body["error"]
            raise ZabbixAPIError(
                method,
                int(error.get("code", 0)),
                str(error.get("message", "")),
                str(error.get("data", "")),
            )
        return body["result"]

    async def version(self) -> str:
        # apiinfo.version refuses a request that carries an Authorization header.
        return await self.call("apiinfo.version", token=None)
