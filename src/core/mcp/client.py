import json
from dataclasses import dataclass
from uuid import uuid4

import httpx

# Newest revision this client knows how to speak. Only a proposal -- the server answers
# with the version it will actually use, which is what we honour.
LATEST_PROTOCOL_VERSION = "2025-06-18"


@dataclass(frozen=True)
class McpToolResult:
    text: str
    is_error: bool


class McpError(Exception):
    """A protocol-level failure -- bad method, malformed request, transport error.

    Tool *execution* failures are not this; they come back as McpToolResult(is_error=True)
    so the model can read them and react.
    """


class McpClient:
    """Streamable-HTTP MCP client. Knows nothing about any particular server."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        url: str,
        client_name: str = "the-way",
        client_version: str = "0.1.0",
        protocol_version: str = LATEST_PROTOCOL_VERSION,
    ) -> None:
        self._http = http
        self._url = url
        self._client_name = client_name
        self._client_version = client_version
        self._proposed_version = protocol_version
        self._tools: list[dict] | None = None

        self.protocol_version: str | None = None
        self.server_capabilities: dict = {}
        self.server_info: dict = {}

    async def _rpc(self, method: str, params: dict) -> dict:
        body = {"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params}

        try:
            response = await self._http.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise McpError(f"{method} could not reach the server: {exc}") from exc

        payload = _parse_sse(response.text)

        if payload is not None and "error" in payload:
            error = payload["error"]
            raise McpError(f"{method} failed [{error.get('code')}]: {error.get('message')}")

        if response.is_error:
            raise McpError(
                f"{method} failed with HTTP {response.status_code}: {response.text[:300]}"
            )

        if payload is None:
            raise McpError(
                f"no JSON-RPC payload in response to {method!r} "
                f"(status {response.status_code}): {response.text[:300]}"
            )

        return payload["result"]

    async def initialize(self) -> None:
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": self._proposed_version,
                "capabilities": {},
                "clientInfo": {"name": self._client_name, "version": self._client_version},
            },
        )
        # The server picks the version, not us. Record what it chose.
        self.protocol_version = result.get("protocolVersion")
        self.server_capabilities = result.get("capabilities", {})
        self.server_info = result.get("serverInfo", {})

    async def list_tools(self) -> list[dict]:
        """The tool catalog. Cached -- servers without a `listChanged` capability never
        notify us of changes, so one fetch is enough."""
        if self._tools is None:
            result = await self._rpc("tools/list", {})
            self._tools = result.get("tools", [])
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> McpToolResult:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(
            block.get("text", "")
            for block in result.get("content", [])
            if block.get("type") == "text"
        )
        return McpToolResult(text=text, is_error=bool(result.get("isError")))

    async def aclose(self) -> None:
        await self._http.aclose()


def _parse_sse(raw: str) -> dict | None:
    """The JSON off the first `data:` line of an SSE frame, or a plain JSON body."""
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())

    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
    return None
