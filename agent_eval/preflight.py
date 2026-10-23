"""Checks the target before any money is spent (Phase 4, step 2), and
records what the run is about to be graded against: the server's build,
its tool list, its /healthz version and a fingerprint of its data."""

from typing import Any

import httpx

from agent_eval.mcp_client import call_json, connect
from agent_eval.records import sha256_hex, stable_json


class PreflightError(Exception):
    """The target can't serve this run: unreachable, missing a tool the
    suite needs, or unable to fingerprint its data. Exit 2, nothing spent."""


async def fingerprint(session: Any, target: dict[str, Any]) -> dict[str, Any]:
    """Runs the target's fingerprint queries through the same endpoint the
    agent uses. Two runs with different fingerprints were graded against
    different data and are never compared (Phase 3)."""
    parts: list[dict[str, Any]] = []
    for sql in target["fingerprint_queries"]:
        result = await call_json(session, target["query_tool"], {"sql": sql})
        if result.get("status") != "succeeded":
            raise PreflightError(f"fingerprint query refused: {result.get('error')}")
        parts.extend(result["rows"])
    return {"sha256": sha256_hex(stable_json(parts)), "parts": parts}


async def preflight(
    target: dict[str, Any], auth_token: str, required_tools: set[str]
) -> dict[str, Any]:
    try:
        async with connect(target["url"], auth_token) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            tools: list[dict[str, Any]] = sorted(
                ({"name": t.name, "input_schema": t.input_schema} for t in listed.tools),
                key=lambda t: str(t["name"]),
            )
            names: set[str] = {str(t["name"]) for t in tools}
            missing = required_tools - names
            if missing:
                raise PreflightError(
                    f"target has no tool(s) {sorted(missing)}; it has {sorted(names)}"
                )
            data = await fingerprint(session, target) if target.get("fingerprint_queries") else None
    except PreflightError:
        raise
    except Exception as exc:  # any other failure to reach the server is a preflight failure
        raise PreflightError(f"can't reach {target['url']}: {type(exc).__name__}") from exc

    healthz_version: str | None = None
    if target.get("healthz_url"):
        try:
            healthz_version = httpx.get(target["healthz_url"], timeout=10).json().get("version")
        except (httpx.HTTPError, ValueError):
            healthz_version = None

    return {
        "server_name": init.server_info.name,
        # "" until MCP-backbone's feat/server-version is deployed; recorded
        # as-is rather than guessed.
        "server_version": init.server_info.version or None,
        "healthz_version": healthz_version,
        "tool_names": sorted(names),
        "tool_list_sha256": sha256_hex(stable_json(tools)),
        "data_fingerprint": data["sha256"] if data else None,
        "data_fingerprint_parts": data["parts"] if data else None,
    }
