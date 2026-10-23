"""Checks the target before any money is spent (Phase 4, step 2), and
records what the run is about to be graded against: the server's build,
its tool list and, for MCP-backbone, its /healthz version."""

from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client  # pyright: ignore[reportPrivateUsage]

from agent_eval.records import canonical_json, sha256_hex


class PreflightError(Exception):
    """The target can't serve this run: unreachable, or missing a tool the
    suite or agent config needs. Exit 2, nothing spent."""


async def preflight(
    target: dict[str, Any], auth_token: str, required_tools: set[str]
) -> dict[str, Any]:
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {auth_token}"})
    try:
        async with (
            http,
            streamable_http_client(target["url"], http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            init = await session.initialize()
            listed = await session.list_tools()
    except Exception as exc:  # any failure to reach the server is a preflight failure
        raise PreflightError(f"can't reach {target['url']}: {type(exc).__name__}") from exc

    tools: list[dict[str, Any]] = sorted(
        ({"name": t.name, "input_schema": t.input_schema} for t in listed.tools),
        key=lambda t: str(t["name"]),
    )
    names: set[str] = {str(t["name"]) for t in tools}
    missing = required_tools - names
    if missing:
        raise PreflightError(f"target has no tool(s) {sorted(missing)}; it has {sorted(names)}")

    healthz_version: str | None = None
    if target.get("healthz_url"):
        try:
            response = httpx.get(target["healthz_url"], timeout=10)
            healthz_version = response.json().get("version")
        except (httpx.HTTPError, ValueError):
            healthz_version = None

    return {
        "server_name": init.server_info.name,
        # "" until MCP-backbone's feat/server-version is deployed; recorded
        # as-is rather than guessed.
        "server_version": init.server_info.version or None,
        "healthz_version": healthz_version,
        "tool_names": sorted(names),
        "tool_list_sha256": sha256_hex(canonical_json(tools)),
    }
