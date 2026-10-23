"""The MCP servers the harness knows how to evaluate against. Keys are
named, never stored: each is read from its environment variable at run
time (Phase 3: no secrets in records)."""

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Run at the start of every run, through the same endpoint the agent uses.
# Each hashes columns with no timestamps in them, so the result doesn't
# depend on the server's session time zone (Spike 4).
_PAGILA_FINGERPRINT = [
    "select (select count(*) from customer) as customers, (select count(*) from film) as films,"
    " (select count(*) from rental) as rentals, (select count(*) from payment) as payments,"
    " (select max(rental_id) from rental) as max_rental_id,"
    " (select max(payment_id) from payment) as max_payment_id",
    "select md5(string_agg(customer_id || ',' || first_name || ',' || last_name || ','"
    " || coalesce(email, ''), '|' order by customer_id)) as customers_md5 from customer",
    "select md5(string_agg(film_id || ',' || title || ',' || rental_rate || ',' || coalesce(length, 0)"
    " || ',' || rating, '|' order by film_id)) as films_md5 from film",
    "select md5(string_agg(rental_id || ',' || inventory_id || ',' || customer_id, '|'"
    " order by rental_id)) as rentals_md5 from rental",
    "select md5(string_agg(payment_id || ',' || amount || ',' || customer_id, '|'"
    " order by payment_id)) as payments_md5 from payment",
]

TARGETS: dict[str, dict[str, Any]] = {
    "mcp-backbone": {
        "name": "mcp-backbone",
        "url": "https://mcp.my.id/mcp/",
        "healthz_url": "https://mcp.my.id/healthz",
        "auth_env": "MCP_BACKBONE_EVAL_KEY",
        # A tool result containing one of these is the server refusing for
        # its own reasons, not the agent being wrong: the trial becomes an
        # `error`, never a `fail` (ADR-007). MCP-backbone says "rate limit
        # of N requests per window exceeded".
        "infra_error_patterns": ["rate limit of"],
        "query_tool": "run_query",
        "fingerprint_queries": _PAGILA_FINGERPRINT,
    },
    # The reference MCP filesystem server (pinned in tools/fs-server), on a
    # fresh copy of a synthetic fixture per trial (agent_eval/fs_server.py).
    # The fixture is made up, so the model can't know it from training: its
    # tools are genuinely needed, unlike Pagila's (see the slice D proofs).
    "filesystem": {
        "name": "filesystem",
        "transport": "stdio",
        "fixture": str(REPO_ROOT / "suites" / "fixtures" / "acme-shop"),
        "auth_env": None,
        "infra_error_patterns": [],
        "write_tools": ["write_file", "edit_file", "create_directory", "move_file"],
        "discovery_tools": ["list_directory", "list_directory_with_sizes", "directory_tree",
                            "search_files"],
    },
}
