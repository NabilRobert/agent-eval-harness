"""Checks the target before any money is spent (Phase 4, step 2), and
records what the run is about to be graded against: the server's build,
its tool list, its /healthz version and a fingerprint of its data."""

from typing import Any

import hashlib
import sys
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.types import ListToolsResult
from mcp.client.stdio import stdio_client

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


def fixture_fingerprint(fixture: Path) -> dict[str, Any]:
    """A fixture's identity: every file's relative path and content hash.
    Any edit to the fixture changes it, so runs on different fixtures are
    never compared."""
    files = {
        str(p.relative_to(fixture)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(fixture.rglob("*"))
        if p.is_file()
    }
    return {"sha256": sha256_hex(stable_json(files)), "parts": [{"files": len(files)}]}


def stdio_params(target: dict[str, Any]) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "agent_eval.fs_server", target["fixture"]]
    )


def _checked_tool_list(
    listed: ListToolsResult, required: set[str]
) -> tuple[list[dict[str, Any]], set[str]]:
    """The server's tools (name and input schema, sorted, the form that's
    hashed into provenance) and their names; PreflightError if a tool the
    suite needs is missing."""
    tools: list[dict[str, Any]] = sorted(
        ({"name": t.name, "input_schema": t.input_schema} for t in listed.tools),
        key=lambda t: str(t["name"]),
    )
    names = {str(t["name"]) for t in tools}
    missing = required - names
    if missing:
        raise PreflightError(f"target has no tool(s) {sorted(missing)}; it has {sorted(names)}")
    return tools, names


async def _preflight_stdio(target: dict[str, Any], required: set[str]) -> dict[str, Any]:
    try:
        async with stdio_client(stdio_params(target)) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                listed = await session.list_tools()
    except Exception as exc:  # the server failed to start: preflight failure
        raise PreflightError(
            f"can't start the {target['name']} server: {type(exc).__name__}"
        ) from exc
    tools, names = _checked_tool_list(listed, required)
    data = fixture_fingerprint(Path(target["fixture"]))
    return {
        "server_name": init.server_info.name,
        "server_version": init.server_info.version or None,
        "healthz_version": None,
        "tool_names": sorted(names),
        "tool_list_sha256": sha256_hex(stable_json(tools)),
        "data_fingerprint": data["sha256"],
        "data_fingerprint_parts": data["parts"],
    }


async def preflight(
    target: dict[str, Any], auth_token: str, required_tools: set[str]
) -> dict[str, Any]:
    if target.get("transport") == "stdio":
        return await _preflight_stdio(target, required_tools)
    try:
        async with connect(target["url"], auth_token) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            tools, names = _checked_tool_list(listed, required_tools)
            if target.get("fingerprint_queries"):
                data = await fingerprint(session, target)
            elif target.get("fixture"):  # an HTTP route to a fixture-backed server (the gateway)
                data = fixture_fingerprint(Path(target["fixture"]))
            else:
                data = None
            utc_offset: int | None = None
            if target.get("utc_offset_query"):
                result = await call_json(
                    session, target["query_tool"], {"sql": target["utc_offset_query"]}
                )
                if result.get("status") != "succeeded":
                    raise PreflightError(f"UTC offset query refused: {result.get('error')}")
                utc_offset = int(float(result["rows"][0]["utc_offset_seconds"]))
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
        "session_utc_offset": utc_offset,
    }
