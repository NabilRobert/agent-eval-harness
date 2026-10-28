"""A stand-in for MCP-backbone over stdio, for the tracing tests: the same
two tool names and the same JSON result shape, with no database. Each
result also says which `traceparent` arrived in the request's `_meta`, so
a test can check that the trace context reached the server.

    python tests/stub_pagila_server.py
"""

import json

from mcp.server.mcpserver import Context, MCPServer

server = MCPServer("stub-pagila")


def _received_traceparent(ctx: Context) -> str | None:
    meta = ctx.request_context.meta or {}
    value = meta.get("traceparent")
    return value if isinstance(value, str) else None


@server.tool()
def list_tables(ctx: Context) -> str:
    """Lists the database's tables."""
    return json.dumps(
        {"status": "succeeded", "tables": ["film"], "traceparent": _received_traceparent(ctx)}
    )


@server.tool()
def run_query(sql: str, ctx: Context) -> str:
    """Runs one read-only SQL query."""
    return json.dumps(
        {
            "status": "succeeded",
            "rows": [{"count": 1000}],
            "traceparent": _received_traceparent(ctx),
        }
    )


if __name__ == "__main__":
    server.run("stdio")
