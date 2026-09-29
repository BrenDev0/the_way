from contextlib import asynccontextmanager

import httpx

from src.core.mcp.client import McpClient, McpError

from . import config


class CXConnection:
    """One user's CX sub-account, reached over the vendor's MCP server.

    The server accepts `initialize` without checking the token, so a wrong one is not
    caught when connecting -- it surfaces as a 401 on the first real operation, which is
    reported to the model as a permissions problem rather than a query problem.
    """

    def __init__(self, token: str, location_id: str) -> None:
        self._token = token
        self.location_id = location_id

    @asynccontextmanager
    async def session(self):
        http = httpx.AsyncClient(
            timeout=config.MCP_TIMEOUT_SECONDS,
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self._token}",
                "locationId": self.location_id,
            },
        )
        client = McpClient(http=http, url=config.MCP_URL)
        try:
            await client.initialize()
            yield client
        finally:
            await client.aclose()

    async def call(self, name: str, arguments: dict, client: McpClient | None = None) -> str:
        """One path to the MCP server for every CX tool, so the error shape is the same
        everywhere. Pass an open client to reuse it across a page loop."""
        if client is None:
            async with self.session() as opened:
                return await self.call(name, arguments, opened)

        # None is "not supplied", which is not the same as an explicit null the server
        # would have to interpret -- drop those rather than sending them.
        payload = {key: value for key, value in arguments.items() if value is not None}

        try:
            result = await client.call_tool(name=name, arguments=payload)
        except McpError as exc:
            return f"{name} failed: {exc}"

        if result.is_error:
            return f"{name} failed: {result.text}"
        return result.text

    async def search(self, query, domains=None, kind=None, limit=None, client=None) -> str:
        return await self.call(
            "search_operations",
            {"query": query, "domains": domains, "kind": kind, "limit": limit},
            client,
        )

    async def describe(self, operation_id: str, client: McpClient | None = None) -> str:
        return await self.call("describe_operation", {"operationId": operation_id}, client)

    async def execute(
        self,
        operation_id: str,
        params: dict | None = None,
        dry_run: bool = False,
        reason: str = "",
        idempotency_key: str | None = None,
        client: McpClient | None = None,
    ) -> str:
        return await self.call(
            "execute_operation",
            {
                "operationId": operation_id,
                "params": params or {},
                "dryRun": dry_run or None,
                "reason": reason or None,
                "idempotencyKey": idempotency_key,
            },
            client,
        )
