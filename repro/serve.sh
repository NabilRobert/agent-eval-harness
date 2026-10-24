#!/bin/sh
# Starts MCP-backbone with the settings setup_repro.py generated.
set -eu
set -a
. /out/mcp.env
set +a
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
