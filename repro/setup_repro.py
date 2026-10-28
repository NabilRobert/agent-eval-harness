"""One-shot setup for the local MCP-backbone (runs inside the repro image).

Uses MCP-backbone's own scripts, not re-implementations, for each step:
1. Load Pagila from upstream at a pinned commit (load_pagila_dataset.py,
   pointed at that commit instead of `master`).
2. Provision the read-only role (provision_readonly_role.py).
3. Migrate the bookkeeping database (alembic).
4. Seed an `eval` workspace with raised rate limits (seed_workspace.py).

Writes /out/mcp.env (the server's settings) and /out/repro.env (the
harness's key for this local server). Runs once; a second run is a no-op.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

ADMIN = "postgresql://postgres:repro@db:5432"
OUT = Path("/out")
DONE = OUT / ".setup-done"


def psql(sql: str, db: str = "postgres") -> None:
    subprocess.run(["psql", f"{ADMIN}/{db}", "-v", "ON_ERROR_STOP=1", "-qc", sql], check=True)


def main() -> int:
    if DONE.exists():
        print("already set up (`docker compose down -v` to start over)")
        return 0
    commit = os.environ["PAGILA_COMMIT"]
    OUT.mkdir(exist_ok=True)

    print(f"== loading Pagila at upstream commit {commit}")
    psql("CREATE DATABASE pagila")
    psql("CREATE DATABASE bookkeeping")
    import scripts.load_pagila_dataset as loader

    base = f"https://raw.githubusercontent.com/devrimgunduz/pagila/{commit}"
    loader.SCHEMA_URL = f"{base}/pagila-schema.sql"
    loader.DATA_URL = f"{base}/pagila-data.sql"
    loader.load("psql", f"{ADMIN}/pagila", Path("/tmp/pagila-cache"), scrub=False)

    print("== provisioning the read-only role")
    from scripts.provision_readonly_role import provision

    ro_password = asyncio.run(provision(f"{ADMIN}/pagila", "pagila_ro", "pagila", "public"))

    from cryptography.fernet import Fernet

    settings = {
        "APP_DATABASE_URL": "postgresql+asyncpg://postgres:repro@db:5432/bookkeeping",
        "APP_TARGET_DATABASE_URL": f"postgresql+asyncpg://pagila_ro:{ro_password}@db:5432/pagila",
        "APP_CONNECTION_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        # The target database is on the Compose network, a private address.
        "APP_ALLOW_PRIVATE_TARGETS": "true",
    }
    (OUT / "mcp.env").write_text("".join(f"{k}={v}\n" for k, v in settings.items()))
    env = {**os.environ, **settings}

    print("== migrating the bookkeeping database")
    subprocess.run(["alembic", "upgrade", "head"], cwd="/app", env=env, check=True)

    print("== seeding the eval workspace")
    key = (
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import asyncio; from scripts.seed_workspace import seed; "
                "print(asyncio.run(seed('eval', None, 'eval', __import__('secrets').token_urlsafe(16), 2000, 2000)))",
            ],
            cwd="/app",
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()[-1]
    )
    (OUT / "repro.env").write_text(f"MCP_BACKBONE_LOCAL_KEY={key}\n")
    DONE.write_text(f"pagila {commit}\n")
    print("== done: the server starts next; the harness reads its key from the out volume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
