"""A small MCP client for the harness's own calls (preflight, the data
fingerprint, generating expected answers). The agent's calls go through
Inspect, not this."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client  # pyright: ignore[reportPrivateUsage]


@asynccontextmanager
async def connect(url: str, auth_token: str) -> AsyncIterator[ClientSession]:
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {auth_token}"})
    async with (
        http,
        streamable_http_client(url, http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        yield session


async def call_json(session: ClientSession, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """A tool's result as a dict (MCP-backbone returns JSON)."""
    result = await session.call_tool(tool, arguments)
    structured = getattr(result, "structured_content", None)
    data: Any = structured if structured else json.loads(result.content[0].text)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]
    if isinstance(data, dict) and "result" in data and len(cast(dict[str, Any], data)) == 1:
        data = cast(dict[str, Any], data)["result"]
    return cast(dict[str, Any], data)
