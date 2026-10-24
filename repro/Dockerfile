# MCP-backbone at a pinned commit, built from its own lockfile, plus psql
# for loading Pagila. Every version here is exact, so a rebuild months
# from now is the same server (ADR-010).
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.13.1

ARG MCP_BACKBONE_COMMIT=4e418e915693ca5a2eba52d469cd4e009988e096
RUN git clone https://github.com/NabilRobert/MCP-backbone /app \
 && git -C /app checkout --detach "$MCP_BACKBONE_COMMIT"
WORKDIR /app
RUN uv sync --frozen --no-dev

COPY setup_repro.py serve.sh /repro/
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app
