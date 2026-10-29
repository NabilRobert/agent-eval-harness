"""agent-eval-harness: regression-gated evaluation of a model plus an MCP
server's tools, run on Inspect AI."""

from pathlib import Path

# The checkout (or the image's /app): suites, runs and prices are found
# relative to it.
REPO_ROOT = Path(__file__).resolve().parent.parent
